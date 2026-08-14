# -*- coding: utf-8 -*-

"""
Linux-compatible DOCX to PDF converter.

Uses LibreOffice instead of Microsoft Word COM automation.
Works on Render/Linux and does not require pythoncom or win32com.
"""

import os
import shutil
import subprocess
from pathlib import Path


class WordConverter:
    """
    Converts DOCX files to PDF using LibreOffice.

    Compatible with:
    - Render
    - Linux
    - Docker

    Does NOT require:
    - Microsoft Word
    - pythoncom
    - win32com
    """

    def __init__(self):
        self.libreoffice = (
            shutil.which("libreoffice")
            or shutil.which("soffice")
        )

    # ---------------------------------------------------
    # Context Manager
    # ---------------------------------------------------

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    # ---------------------------------------------------
    # Start
    # ---------------------------------------------------

    def start(self):

        if not self.libreoffice:
            raise RuntimeError(
                "LibreOffice was not found. "
                "Make sure LibreOffice is installed in the Docker image."
            )

    # ---------------------------------------------------
    # Convert One File
    # ---------------------------------------------------

    def convert(self, docx_path, pdf_path):

        docx_path = Path(docx_path).resolve()
        pdf_path = Path(pdf_path).resolve()

        if not docx_path.exists():
            return False, f"Document not found:\n{docx_path}"

        pdf_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        try:

            command = [
                self.libreoffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pdf_path.parent),
                str(docx_path),
            ]

            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:

                error_message = (
                    result.stderr.strip()
                    or result.stdout.strip()
                    or "LibreOffice conversion failed."
                )

                return False, error_message

            generated_pdf = (
                pdf_path.parent /
                f"{docx_path.stem}.pdf"
            )

            if not generated_pdf.exists():
                return False, (
                    "LibreOffice completed but "
                    "the PDF file was not created."
                )

            # LibreOffice creates the PDF using the DOCX filename.
            # Rename it to the exact requested filename if necessary.
            if generated_pdf.resolve() != pdf_path.resolve():

                if pdf_path.exists():
                    pdf_path.unlink()

                generated_pdf.rename(pdf_path)

            return True, "OK"

        except subprocess.TimeoutExpired:
            return False, "LibreOffice conversion timed out."

        except Exception as ex:
            return False, str(ex)

    # ---------------------------------------------------
    # Batch Convert
    # ---------------------------------------------------

    def convert_many(self, jobs):

        results = []

        for docx_path, pdf_path in jobs:

            results.append(
                self.convert(
                    docx_path,
                    pdf_path
                )
            )

        return results

    # ---------------------------------------------------
    # Close
    # ---------------------------------------------------

    def close(self):
        """
        No persistent LibreOffice process is maintained.
        Each conversion runs LibreOffice headlessly.
        """
        pass
