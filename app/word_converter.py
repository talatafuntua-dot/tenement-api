# -*- coding: utf-8 -*-
"""Linux-compatible DOCX-to-PDF conversion using LibreOffice.

Bulk conversion sends a controlled group of DOCX files to one LibreOffice
process instead of starting LibreOffice once for every bill.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path


class WordConverter:
    """Convert DOCX files to PDF on Linux/Render using LibreOffice."""

    def __init__(self, batch_size=25, timeout=600):
        self.libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
        self.batch_size = max(1, int(batch_size))
        self.timeout = max(30, int(timeout))

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def start(self):
        if not self.libreoffice:
            raise RuntimeError(
                "LibreOffice was not found. Make sure it is installed in the Docker image."
            )

    def _run_conversion(self, docx_paths, output_dir):
        """Run one LibreOffice process for all input files in this group."""
        self.start()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # A private profile prevents collisions with another conversion process.
        with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile_dir:
            command = [
                self.libreoffice,
                "--headless",
                f"-env:UserInstallation={Path(profile_dir).resolve().as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                *[str(Path(path).resolve()) for path in docx_paths],
            ]
            try:
                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return False, "LibreOffice batch conversion timed out."
            except Exception as exc:
                return False, str(exc)

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            return False, message or f"LibreOffice exited with code {result.returncode}."

        return True, result.stdout.strip() or "OK"

    def convert(self, docx_path, pdf_path):
        """Convert one DOCX. Kept for the existing individual-bill workflow."""
        docx_path = Path(docx_path).resolve()
        pdf_path = Path(pdf_path).resolve()

        if not docx_path.is_file():
            return False, f"Document not found: {docx_path}"

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="lo_single_") as output_dir:
            ok, message = self._run_conversion([docx_path], output_dir)
            if not ok:
                return False, message

            generated_pdf = Path(output_dir) / f"{docx_path.stem}.pdf"
            if not generated_pdf.is_file():
                return False, "LibreOffice completed but the PDF file was not created."

            try:
                if pdf_path.exists():
                    pdf_path.unlink()
                shutil.move(str(generated_pdf), str(pdf_path))
            except Exception as exc:
                return False, f"Could not place generated PDF: {exc}"

        return True, "OK"

    def convert_many(self, jobs):
        """Convert (DOCX, PDF) jobs in groups, launching LibreOffice once per group.

        Returns one (success, message) tuple for each input job, in input order.
        Output PDF names may differ from DOCX names; each is moved to its requested
        destination after the batch has completed.
        """
        jobs = [(Path(src).resolve(), Path(dst).resolve()) for src, dst in jobs]
        results = [None] * len(jobs)

        if not jobs:
            return results

        self.start()

        for start in range(0, len(jobs), self.batch_size):
            group = jobs[start:start + self.batch_size]
            valid_group = []

            for offset, (docx_path, pdf_path) in enumerate(group):
                result_index = start + offset
                if not docx_path.is_file():
                    results[result_index] = (False, f"Document not found: {docx_path}")
                    continue
                valid_group.append((result_index, docx_path, pdf_path))

            if not valid_group:
                continue

            # LibreOffice writes output files using the input DOCX stems.
            # Bulk caller uses unique DOCX stems, avoiding filename collisions.
            stems = [src.stem.casefold() for _, src, _ in valid_group]
            if len(stems) != len(set(stems)):
                for result_index, _, _ in valid_group:
                    results[result_index] = (
                        False,
                        "DOCX filenames in the same conversion batch must be unique.",
                    )
                continue

            with tempfile.TemporaryDirectory(prefix="lo_batch_") as output_dir:
                ok, message = self._run_conversion(
                    [src for _, src, _ in valid_group], output_dir
                )

                if not ok:
                    for result_index, _, _ in valid_group:
                        results[result_index] = (False, message)
                    continue

                for result_index, docx_path, pdf_path in valid_group:
                    generated_pdf = Path(output_dir) / f"{docx_path.stem}.pdf"
                    if not generated_pdf.is_file():
                        results[result_index] = (
                            False,
                            f"LibreOffice did not create {generated_pdf.name}.",
                        )
                        continue
                    try:
                        pdf_path.parent.mkdir(parents=True, exist_ok=True)
                        if pdf_path.exists():
                            pdf_path.unlink()
                        shutil.move(str(generated_pdf), str(pdf_path))
                        results[result_index] = (True, "OK")
                    except Exception as exc:
                        results[result_index] = (
                            False,
                            f"Could not save PDF {pdf_path}: {exc}",
                        )

        return [item if item is not None else (False, "Conversion was not attempted.") for item in results]

    def close(self):
        """No persistent LibreOffice process is kept between conversion groups."""
        pass
