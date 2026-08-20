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
✓ Clean Word paragraph pagination properties
✓ Prevent unnecessary paragraph/page breaks
✓ Prevent table rows from splitting where possible
"""

import re
from copy import deepcopy
from docx import Document


PLACEHOLDER_PATTERN = re.compile(r"\{\{(.*?)\}\}")


class TemplateEngine:

    def __init__(self):
        self.missing_placeholders = set()

    # =================================================
    # PUBLIC API
    # =================================================

    def render(
        self,
        template_path,
        output_path,
        data
    ):

        doc = Document(template_path)

        # -------------------------------------------------
        # Replace placeholders
        # -------------------------------------------------

        self._process_document(
            doc,
            data
        )

        # -------------------------------------------------
        # Pagination / layout cleanup
        # -------------------------------------------------

        self._cleanup_document_layout(doc)

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        doc.save(output_path)

        return sorted(
            self.missing_placeholders
        )

    # =================================================
    # DOCUMENT
    # =================================================

    def _process_document(
        self,
        doc,
        data
    ):

        # -------------------------------------------------
        # Main document paragraphs
        # -------------------------------------------------

        for paragraph in doc.paragraphs:

            self._replace_paragraph(
                paragraph,
                data
            )

        # -------------------------------------------------
        # Main document tables
        # -------------------------------------------------

        for table in doc.tables:

            self._process_table(
                table,
                data
            )

        # -------------------------------------------------
        # Headers / Footers
        # -------------------------------------------------

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

    # =================================================
    # TABLE PROCESSING
    # =================================================

    def _process_table(
        self,
        table,
        data
    ):

        for row in table.rows:

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

                for nested in cell.tables:

                    self._process_table(
                        nested,
                        data
                    )

    # =================================================
    # PARAGRAPH REPLACEMENT
    # =================================================

    def _replace_paragraph(
        self,
        paragraph,
        data
    ):

        if not paragraph.text:

            return

        original = paragraph.text

        updated = original

        placeholders = (
            PLACEHOLDER_PATTERN.findall(
                original
            )
        )

        for key in placeholders:

            clean_key = (
                key.strip().upper()
            )

            placeholder = (
                "{{" +
                key +
                "}}"
            )

            if clean_key in data:

                updated = updated.replace(
                    placeholder,
                    str(data[clean_key])
                )

            else:

                self.missing_placeholders.add(
                    clean_key
                )

        # Nothing changed
        if updated == original:

            return

        # -------------------------------------------------
        # Preserve formatting of first run
        # -------------------------------------------------

        first_style = None

        if paragraph.runs:

            first_style = deepcopy(
                paragraph.runs[0]
                ._element
                .rPr
            )

        # -------------------------------------------------
        # Remove existing runs
        # -------------------------------------------------

        while paragraph.runs:

            run = (
                paragraph.runs[0]
                ._element
            )

            run.getparent().remove(
                run
            )

        # -------------------------------------------------
        # Add replaced text
        # -------------------------------------------------

        new_run = paragraph.add_run(
            updated
        )

        # -------------------------------------------------
        # Restore formatting
        # -------------------------------------------------

        if first_style is not None:

            new_run\
                ._element\
                .get_or_add_rPr()\
                .append(first_style)

    # =================================================
    # PAGINATION CLEANUP
    # =================================================

    def _cleanup_document_layout(
        self,
        doc
    ):

        # -------------------------------------------------
        # Main document
        # -------------------------------------------------

        self._cleanup_paragraphs(
            doc.paragraphs
        )

        for table in doc.tables:

            self._cleanup_table(
                table
            )

        # -------------------------------------------------
        # Headers / Footers
        # -------------------------------------------------

        for section in doc.sections:

            self._cleanup_paragraphs(
                section.header.paragraphs
            )

            for table in section.header.tables:

                self._cleanup_table(
                    table
                )

            self._cleanup_paragraphs(
                section.footer.paragraphs
            )

            for table in section.footer.tables:

                self._cleanup_table(
                    table
                )

    # =================================================
    # PARAGRAPH PAGINATION
    # =================================================

    def _cleanup_paragraphs(
        self,
        paragraphs
    ):

        for paragraph in paragraphs:

            self._cleanup_paragraph(
                paragraph
            )

    # =================================================
    # SINGLE PARAGRAPH
    # =================================================

    def _cleanup_paragraph(
        self,
        paragraph
    ):

        format_ = paragraph.paragraph_format

        # -------------------------------------------------
        # Do NOT allow an unnecessary page break
        # -------------------------------------------------

        format_.page_break_before = False

        # -------------------------------------------------
        # Do not force a paragraph to stay with the
        # following paragraph.
        #
        # This is important around the final signature
        # section because Word may otherwise move a group
        # of paragraphs to the next page.
        # -------------------------------------------------

        format_.keep_with_next = False

        # -------------------------------------------------
        # Keep individual paragraph together.
        #
        # This prevents a paragraph itself from breaking
        # awkwardly across pages.
        # -------------------------------------------------

        format_.keep_together = True

        # -------------------------------------------------
        # Remove excessive paragraph spacing only when
        # explicitly present.
        #
        # We preserve normal template spacing.
        # -------------------------------------------------

        if format_.space_after is not None:

            if format_.space_after.pt > 12:

                format_.space_after = None

        if format_.space_before is not None:

            if format_.space_before.pt > 12:

                format_.space_before = None

    # =================================================
    # TABLE CLEANUP
    # =================================================

    def _cleanup_table(
        self,
        table
    ):

        for row in table.rows:

            self._prevent_row_split(
                row
            )

            for cell in row.cells:

                # -------------------------------------------------
                # Cell paragraphs
                # -------------------------------------------------

                for paragraph in cell.paragraphs:

                    self._cleanup_paragraph(
                        paragraph
                    )

                # -------------------------------------------------
                # Nested tables
                # -------------------------------------------------

                for nested in cell.tables:

                    self._cleanup_table(
                        nested
                    )

    # =================================================
    # PREVENT TABLE ROW SPLITTING
    # =================================================

    def _prevent_row_split(
        self,
        row
    ):

        """
        Tell Word that this table row should stay together.

        This is especially useful for:
        - rate tables
        - signature tables
        - nested tables
        """

        trPr = row._tr.get_or_add_trPr()

        # Remove an existing cantSplit element first
        for child in list(trPr):

            if child.tag.endswith(
                "cantSplit"
            ):

                trPr.remove(
                    child
                )

        # Add cantSplit
        from docx.oxml import OxmlElement

        cant_split = (
            OxmlElement(
                "w:cantSplit"
            )
        )

        trPr.append(
            cant_split
        )
