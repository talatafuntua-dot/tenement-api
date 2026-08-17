# -*- coding: utf-8 -*-
"""
template_engine.py
Advanced Word template engine.

Features
--------
✓ Replace placeholders in paragraphs
✓ Replace placeholders in tables
✓ Replace placeholders in nested tables
✓ Replace placeholders in headers
✓ Replace placeholders in footers
✓ Detect unresolved placeholders
"""

import re
from docx import Document


PLACEHOLDER_PATTERN = re.compile(r"\{\{(.*?)\}\}")


class TemplateEngine:

    def __init__(self):
        self.missing_placeholders = set()

    # -------------------------------------------------
    # Public API
    # -------------------------------------------------

    def render(self, template_path, output_path, data):

        # Load the original Word template
        doc = Document(template_path)

        # Process all document content
        self._process_document(doc, data)

        # Save the modified document
        doc.save(output_path)

        return sorted(self.missing_placeholders)

    # -------------------------------------------------
    # Document
    # -------------------------------------------------

    def _process_document(self, doc, data):

        # Main document paragraphs
        for paragraph in doc.paragraphs:
            self._replace_paragraph(paragraph, data)

        # Main document tables
        for table in doc.tables:
            self._process_table(table, data)

        # Headers and footers
        for section in doc.sections:

            # Header paragraphs
            for paragraph in section.header.paragraphs:
                self._replace_paragraph(paragraph, data)

            # Header tables
            for table in section.header.tables:
                self._process_table(table, data)

            # Footer paragraphs
            for paragraph in section.footer.paragraphs:
                self._replace_paragraph(paragraph, data)

            # Footer tables
            for table in section.footer.tables:
                self._process_table(table, data)

    # -------------------------------------------------
    # Tables
    # -------------------------------------------------

    def _process_table(self, table, data):

        for row in table.rows:

            for cell in row.cells:

                # Paragraphs directly inside the cell
                for paragraph in cell.paragraphs:
                    self._replace_paragraph(paragraph, data)

                # Nested tables
                for nested in cell.tables:
                    self._process_table(nested, data)

    # -------------------------------------------------
    # Paragraph replacement
    # -------------------------------------------------

    def _replace_paragraph(self, paragraph, data):

        if not paragraph.runs:
            return

        # -------------------------------------------------
        # Replace placeholders inside existing runs.
        #
        # IMPORTANT:
        # We do NOT delete and recreate the runs.
        #
        # This preserves the original Word template
        # structure and formatting.
        # -------------------------------------------------

        for run in paragraph.runs:

            if not run.text:
                continue

            original_text = run.text

            placeholders = PLACEHOLDER_PATTERN.findall(
                original_text
            )

            if not placeholders:
                continue

            updated_text = original_text

            for key in placeholders:

                clean_key = key.strip().upper()

                placeholder = "{{" + key + "}}"

                if clean_key in data:

                    updated_text = updated_text.replace(
                        placeholder,
                        str(data[clean_key])
                    )

                else:

                    self.missing_placeholders.add(
                        clean_key
                    )

            # Only modify the run if something actually changed
            if updated_text != original_text:

                run.text = updated_text
