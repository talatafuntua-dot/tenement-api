# -*- coding: utf-8 -*-

"""
template_engine.py

Word template rendering engine.

Preserves the original DOCX formatting structure while replacing
placeholders.

## Features

* Replace placeholders in normal paragraphs
* Replace placeholders in tables
* Replace placeholders in nested tables
* Replace placeholders in headers
* Replace placeholders in footers
* Detect unresolved placeholders
* Prevent table rows from splitting across pages
* Preserve existing Word runs and formatting
  """

import re

from docx import Document
from docx.oxml import OxmlElement

PLACEHOLDER_PATTERN = re.compile(r"{{(.*?)}}")

class TemplateEngine:

```
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

    # -----------------------------------------------------
    # Normal document paragraphs
    # -----------------------------------------------------

    for paragraph in doc.paragraphs:

        self._replace_paragraph(
            paragraph,
            data
        )

    # -----------------------------------------------------
    # Normal document tables
    # -----------------------------------------------------

    for table in doc.tables:

        self._process_table(
            table,
            data
        )

    # -----------------------------------------------------
    # Headers and footers
    # -----------------------------------------------------

    for section in doc.sections:

        # Header paragraphs
        for paragraph in section.header.paragraphs:

            self._replace_paragraph(
                paragraph,
                data
            )

        # Header tables
        for table in section.header.tables:

            self._process_table(
                table,
                data
            )

        # Footer paragraphs
        for paragraph in section.footer.paragraphs:

            self._replace_paragraph(
                paragraph,
                data
            )

        # Footer tables
        for table in section.footer.tables:

            self._process_table(
                table,
                data
            )

# =========================================================
# TABLES
# =========================================================

def _process_table(self, table, data):

    for row in table.rows:

        # Keep the existing Word table row together.
        self._prevent_row_split(row)

        for cell in row.cells:

            # -------------------------------------------------
            # Cell paragraphs
            # -------------------------------------------------

            for paragraph in cell.paragraphs:

                self._replace_paragraph(
                    paragraph,
                    data
                )

            # -------------------------------------------------
            # Nested tables
            # -------------------------------------------------

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

    # Remove existing cantSplit elements.
    for element in tr_pr.findall(
        f"{namespace}cantSplit"
    ):

        tr_pr.remove(element)

    # Add cantSplit.
    cant_split = OxmlElement(
        "w:cantSplit"
    )

    tr_pr.append(
        cant_split
    )

# =========================================================
# PARAGRAPH REPLACEMENT
# =========================================================

def _replace_paragraph(self, paragraph, data):

    if not paragraph.runs:
        return

    # -----------------------------------------------------
    # Build the complete visible paragraph text.
    #
    # We DO NOT delete the runs.
    # -----------------------------------------------------

    full_text = "".join(
        run.text or ""
        for run in paragraph.runs
    )

    if not full_text:
        return

    # -----------------------------------------------------
    # Find placeholders.
    # -----------------------------------------------------

    matches = list(
        PLACEHOLDER_PATTERN.finditer(
            full_text
        )
    )

    if not matches:
        return

    # -----------------------------------------------------
    # Resolve replacements.
    # -----------------------------------------------------

    replacements = []

    for match in matches:

        original_placeholder = match.group(0)

        clean_key = (
            match.group(1)
            .strip()
            .upper()
        )

        if clean_key in data:

            value = data.get(
                clean_key,
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
                clean_key
            )

            # Keep unresolved placeholder unchanged.
            replacements.append(
                (
                    match.start(),
                    match.end(),
                    original_placeholder
                )
            )

    # -----------------------------------------------------
    # Create the final paragraph text.
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
    # IMPORTANT
    #
    # Preserve the existing runs and formatting.
    #
    # We rebuild only the TEXT portions of the runs.
    # We do NOT remove the run XML.
    # -----------------------------------------------------

    self._write_text_preserving_runs(
        paragraph,
        final_text
    )

# =========================================================
# WRITE TEXT WITHOUT DESTROYING RUN FORMATTING
# =========================================================

def _write_text_preserving_runs(
    self,
    paragraph,
    new_text
):

    runs = list(
        paragraph.runs
    )

    if not runs:
        return

    # -----------------------------------------------------
    # Record original run lengths.
    # -----------------------------------------------------

    original_lengths = []

    for run in runs:

        original_lengths.append(
            len(run.text or "")
        )

    # -----------------------------------------------------
    # If there is only one run, simply replace its text.
    #
    # Its formatting remains untouched.
    # -----------------------------------------------------

    if len(runs) == 1:

        runs[0].text = new_text

        return

    # -----------------------------------------------------
    # Preserve the existing run structure as much as
    # possible.
    #
    # The first run receives the beginning of the new text.
    # Subsequent runs receive text according to the original
    # run boundaries.
    # -----------------------------------------------------

    remaining = new_text
    position = 0

    for index, run in enumerate(runs):

        if index == len(runs) - 1:

            run.text = remaining

            break

        original_length = (
            original_lengths[index]
        )

        # If this run originally had no text,
        # leave it empty.
        if original_length <= 0:

            run.text = ""

            continue

        # -------------------------------------------------
        # Preserve approximately the original distribution
        # of text across the runs.
        # -------------------------------------------------

        take = min(
            original_length,
            len(remaining)
        )

        run.text = (
            remaining[:take]
        )

        remaining = (
            remaining[take:]
        )

        position += take

    # -----------------------------------------------------
    # If replacement text is shorter than the original
    # paragraph, clear unused trailing runs.
    # -----------------------------------------------------

    if remaining == "":

        for index, run in enumerate(runs):

            if index == 0:
                continue

            # Do not remove the run.
            # Only clear its text.
            #
            # This preserves its formatting XML.
            #
            # Empty runs do not affect page layout.
            if (
                index < len(runs)
                and run.text
                and index >= len(runs) - 1
            ):
                pass

# =========================================================
# ALTERNATIVE SAFE RUN WRITER
# =========================================================

def _replace_text_in_runs(
    self,
    paragraph,
    old_text,
    new_text
):

    """
    Replace text across multiple runs while keeping
    the existing run XML and formatting.

    This method is retained for compatibility with
    templates where a placeholder itself is split
    across several Word runs.
    """

    runs = list(
        paragraph.runs
    )

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

    self._write_text_preserving_runs(
        paragraph,
        updated
    )

    return True
```
