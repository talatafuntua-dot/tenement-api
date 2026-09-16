
Python is reading those as code, causing:

`IndentationError: expected an indented block after class definition`

Also, I want to correct the implementation before you test again: the previous version was unnecessarily complicated and its run-preservation logic was not robust enough for a Word template.

**Do not test Swagger yet. Replace the file with this clean version.** There are **no Markdown backticks inside the file**.

:::writing{variant="document" id="58321" title="Corrected app/template_engine.py"}
# -*- coding: utf-8 -*-

"""
template_engine.py

Word template rendering engine.

Replaces placeholders while preserving the existing
Word paragraph and run formatting.

Supports:
- Normal paragraphs
- Tables
- Nested tables
- Headers
- Footers
- Unresolved placeholder detection
- Preventing table rows from splitting
"""

import re

from docx import Document
from docx.oxml import OxmlElement


PLACEHOLDER_PATTERN = re.compile(r"\{\{(.*?)\}\}")


class TemplateEngine:

    def __init__(self):
        self.missing_placeholders = set()

    # =========================================================
    # PUBLIC API
    # =========================================================

    def render(self, template_path, output_path, data):

        self.missing_placeholders = set()

        doc = Document(template_path)

        self._process_document(
            doc,
            data
        )

        doc.save(output_path)

        return sorted(
            self.missing_placeholders
        )

    # =========================================================
    # DOCUMENT
    # =========================================================

    def _process_document(self, doc, data):

        for paragraph in doc.paragraphs:

            self._replace_paragraph(
                paragraph,
                data
            )

        for table in doc.tables:

            self._process_table(
                table,
                data
            )

        for section in doc.sections:

            for paragraph in section.header.paragraphs:

                self._replace_paragraph(
                    paragraph,
                    data
                )

            for table in section.header.tables:

                self._process_table(
                    table,
                    data
                )

            for paragraph in section.footer.paragraphs:

                self._replace_paragraph(
                    paragraph,
                    data
                )

            for table in section.footer.tables:

                self._process_table(
                    table,
                    data
                )

    # =========================================================
    # TABLE PROCESSING
    # =========================================================

    def _process_table(self, table, data):

        for row in table.rows:

            self._prevent_row_split(row)

            for cell in row.cells:

                for paragraph in cell.paragraphs:

                    self._replace_paragraph(
                        paragraph,
                        data
                    )

                for nested_table in cell.tables:

                    self._process_table(
                        nested_table,
                        data
                    )

    # =========================================================
    # PREVENT TABLE ROW SPLITTING
    # =========================================================

    def _prevent_row_split(self, row):

        tr_pr = row._tr.get_or_add_trPr()

        namespace = (
            "{http://schemas.openxmlformats.org/"
            "wordprocessingml/2006/main}"
        )

        existing = tr_pr.findall(
            f"{namespace}cantSplit"
        )

        for element in existing:

            tr_pr.remove(element)

        cant_split = OxmlElement(
            "w:cantSplit"
        )

        tr_pr.append(
            cant_split
        )

    # =========================================================
    # REPLACE PARAGRAPH
    # =========================================================

    def _replace_paragraph(self, paragraph, data):

        runs = list(
            paragraph.runs
        )

        if not runs:
            return

        # -----------------------------------------------------
        # Get complete paragraph text.
        #
        # A Word placeholder may be contained in one run or
        # split across several runs.
        # -----------------------------------------------------

        full_text = "".join(
            run.text or ""
            for run in runs
        )

        if not full_text:
            return

        matches = list(
            PLACEHOLDER_PATTERN.finditer(
                full_text
            )
        )

        if not matches:
            return

        # -----------------------------------------------------
        # Build replacement list.
        # -----------------------------------------------------

        replacements = []

        for match in matches:

            placeholder = match.group(0)

            key = (
                match.group(1)
                .strip()
                .upper()
            )

            if key in data:

                value = data.get(
                    key,
                    ""
                )

                if value is None:
                    value = ""

                replacements.append(
                    (
                        match.start(),
                        match.end(),
                        str(value)
                    )
                )

            else:

                self.missing_placeholders.add(
                    key
                )

        # -----------------------------------------------------
        # Nothing to replace.
        # -----------------------------------------------------

        if not replacements:
            return

        # -----------------------------------------------------
        # Produce final text.
        # -----------------------------------------------------

        final_text = full_text

        for start, end, replacement in reversed(
            replacements
        ):

            final_text = (
                final_text[:start]
                + replacement
                + final_text[end:]
            )

        # -----------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT delete paragraph runs.
        #
        # We retain the existing run XML and therefore retain
        # the original Word formatting.
        # -----------------------------------------------------

        self._write_preserving_runs(
            runs,
            final_text
        )

    # =========================================================
    # WRITE TEXT WHILE PRESERVING RUNS
    # =========================================================

    def _write_preserving_runs(
        self,
        runs,
        text
    ):

        if not runs:
            return

        # -----------------------------------------------------
        # The safest case is a single run.
        # -----------------------------------------------------

        if len(runs) == 1:

            runs[0].text = text

            return

        # -----------------------------------------------------
        # Keep the original run boundaries as much as possible.
        #
        # The formatting XML of each run remains untouched.
        # Only the text is changed.
        # -----------------------------------------------------

        original_lengths = [
            len(run.text or "")
            for run in runs
        ]

        remaining = text

        for index, run in enumerate(runs):

            # -------------------------------------------------
            # Last run receives everything remaining.
            # -------------------------------------------------

            if index == len(runs) - 1:

                run.text = remaining

                break

            original_length = (
                original_lengths[index]
            )

            # -------------------------------------------------
            # Empty original run.
            # -------------------------------------------------

            if original_length == 0:

                run.text = ""

                continue

            # -------------------------------------------------
            # Keep approximately the original amount of text
            # in this run.
            # -------------------------------------------------

            amount = min(
                original_length,
                len(remaining)
            )

            run.text = (
                remaining[:amount]
            )

            remaining = (
                remaining[amount:]
            )

    # =========================================================
    # DIRECT MULTI-RUN REPLACEMENT
    # =========================================================

    def _replace_text_in_runs(
        self,
        paragraph,
        old_text,
        new_text
    ):

        runs = list(
            paragraph.runs
        )

        if not runs:
            return False

        combined = "".join(
            run.text or ""
            for run in runs
        )

        if old_text not in combined:

            return False

        updated = combined.replace(
            old_text,
            new_text,
            1
        )

        self._write_preserving_runs(
            runs,
            updated
        )

        return True
:::

### Now do exactly this

1. Open `app/template_engine.py`.
2. **Select everything** in that file.
3. Delete it.
4. Paste the complete file above.
5. Save it.
6. Push/commit it to GitHub.
7. Let Render redeploy.
8. Check the Render deployment log.

The important thing is that the deployment log must **not** contain:

`IndentationError`

Once you see:

`Application startup complete`

and:

`Uvicorn running on http://0.0.0.0:10000`

then **stop there and tell me "started"**.

We will then run the Swagger test.
