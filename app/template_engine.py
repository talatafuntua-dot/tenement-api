from pathlib import Path
import html
import re
import zipfile


class TemplateEngine:
    """
    Surgical DOCX template renderer.

    - Does NOT use python-docx.
    - Does NOT use lxml.
    - Does NOT rebuild paragraphs.
    - Does NOT rebuild tables.
    - Does NOT rebuild drawings/text boxes.

    Placeholder text is replaced directly inside the original
    DOCX XML.

    The bill-information table is additionally forced to use
    fixed table layout so its existing column geometry is preserved.
    """

    TEXT_TAG_PATTERN = re.compile(
        rb"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)",
        re.DOTALL,
    )

    TBL_PATTERN = re.compile(
        rb"<w:tbl\b.*?</w:tbl>",
        re.DOTALL,
    )

    TBL_PR_PATTERN = re.compile(
        rb"<w:tblPr\b[^>]*>",
        re.DOTALL,
    )

    TBL_LAYOUT_PATTERN = re.compile(
        rb"<w:tblLayout\b[^>]*\/?>",
        re.DOTALL,
    )

    BILL_PLACEHOLDER_MARKERS = (
        b"{{ESTIMATED}}",
        b"{{RATE_1}}",
        b"{{RATE_2}}",
        b"{{RATE_3}}",
        b"{{ARREARS_1}}",
        b"{{ARREARS_2}}",
        b"{{ARREARS_3}}",
        b"{{PER_1}}",
        b"{{PER_2}}",
        b"{{PER_3}}",
        b"{{TOTAL_1}}",
        b"{{TOTAL_2}}",
        b"{{TOTAL_3}}",
    )

    def __init__(self):
        self.missing_placeholders = set()

    # ==========================================================
    # PUBLIC METHOD
    # ==========================================================

    def render(self, template_path, output_path, data):

        self.missing_placeholders = set()

        template_path = Path(template_path)
        output_path = Path(output_path)

        if not template_path.is_file():
            raise FileNotFoundError(
                f"Template file not found: {template_path}"
            )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        replacements = self._build_replacements(data)

        with zipfile.ZipFile(
            template_path,
            "r"
        ) as source_zip:

            with zipfile.ZipFile(
                output_path,
                "w",
                compression=zipfile.ZIP_DEFLATED
            ) as destination_zip:

                for item in source_zip.infolist():

                    content = source_zip.read(
                        item.filename
                    )

                    if self._is_word_xml(
                        item.filename
                    ):

                        # --------------------------------------------------
                        # 1. Replace placeholders surgically.
                        # --------------------------------------------------

                        content = self._replace_in_xml(
                            content,
                            replacements
                        )

                        # --------------------------------------------------
                        # 2. Lock ONLY the bill-information table.
                        # --------------------------------------------------

                        content = self._fix_bill_table_layout(
                            content
                        )

                    destination_zip.writestr(
                        item,
                        content
                    )

        return sorted(
            self.missing_placeholders
        )

    # ==========================================================
    # BUILD REPLACEMENTS
    # ==========================================================

    def _build_replacements(self, data):

        if data is None:
            data = {}

        replacements = {}

        for key, value in data.items():

            if key is None:
                continue

            key = str(key).strip()

            if not key:
                continue

            if (
                key.startswith("{{")
                and
                key.endswith("}}")
            ):
                placeholder = key
            else:
                placeholder = (
                    "{{"
                    +
                    key
                    +
                    "}}"
                )

            if value is None:
                value = ""

            replacements[
                placeholder
            ] = self._format_value(value)

        return replacements

    # ==========================================================
    # VALUE FORMATTER
    # ==========================================================

    def _format_value(self, value):

        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, float):

            if value.is_integer():
                return str(
                    int(value)
                )

        return str(value)

    # ==========================================================
    # WORD XML DETECTION
    # ==========================================================

    def _is_word_xml(self, filename):

        return (
            filename.startswith("word/")
            and
            filename.endswith(".xml")
        )

    # ==========================================================
    # SURGICAL TEXT REPLACEMENT
    # ==========================================================

    def _replace_in_xml(
        self,
        xml_bytes,
        replacements
    ):

        matches = list(
            self.TEXT_TAG_PATTERN.finditer(
                xml_bytes
            )
        )

        if not matches:
            return xml_bytes

        nodes = []

        for match in matches:

            raw_text = match.group(2)

            try:
                text = raw_text.decode(
                    "utf-8"
                )
            except UnicodeDecodeError:
                text = raw_text.decode(
                    "utf-8",
                    errors="replace"
                )

            nodes.append(
                {
                    "text": text,
                    "start": match.start(2),
                    "end": match.end(2),
                }
            )

        # ------------------------------------------------------
        # Replace every placeholder.
        # ------------------------------------------------------

        for placeholder, replacement in replacements.items():

            self._replace_placeholder_across_nodes(
                nodes,
                placeholder,
                replacement
            )

        # ------------------------------------------------------
        # Rebuild only the contents of w:t elements.
        #
        # Everything outside those text contents is copied
        # directly from the original XML.
        # ------------------------------------------------------

        output = bytearray()

        previous_end = 0

        for index, match in enumerate(matches):

            node = nodes[index]

            output.extend(
                xml_bytes[
                    previous_end:
                    match.start(2)
                ]
            )

            escaped_text = self._xml_escape(
                node["text"]
            )

            output.extend(
                escaped_text.encode(
                    "utf-8"
                )
            )

            previous_end = match.end(2)

        output.extend(
            xml_bytes[
                previous_end:
            ]
        )

        return bytes(output)

    # ==========================================================
    # PLACEHOLDER REPLACEMENT ACROSS WORD RUNS
    # ==========================================================

    def _replace_placeholder_across_nodes(
        self,
        nodes,
        placeholder,
        replacement
    ):

        if not placeholder:
            return

        search_start = 0

        while search_start < len(nodes):

            combined = ""
            mapping = []

            found = False

            for index in range(
                search_start,
                len(nodes)
            ):

                text = nodes[index]["text"]

                start_position = len(combined)

                combined += text

                end_position = len(combined)

                mapping.append(
                    (
                        index,
                        start_position,
                        end_position
                    )
                )

                if placeholder in combined:

                    found = True
                    break

            if not found:
                break

            placeholder_start = combined.find(
                placeholder
            )

            placeholder_end = (
                placeholder_start
                +
                len(placeholder)
            )

            affected = []

            for index, start, end in mapping:

                if (
                    end > placeholder_start
                    and
                    start < placeholder_end
                ):

                    affected.append(
                        (
                            index,
                            start,
                            end
                        )
                    )

            if not affected:
                break

            first_index = affected[0][0]
            last_index = affected[-1][0]

            first_node = nodes[first_index]
            last_node = nodes[last_index]

            first_node_start = affected[0][1]
            last_node_end = affected[-1][2]

            # --------------------------------------------------
            # Text before placeholder.
            # --------------------------------------------------

            prefix_length = (
                placeholder_start
                -
                first_node_start
            )

            prefix = first_node["text"][
                :prefix_length
            ]

            # --------------------------------------------------
            # Text after placeholder.
            # --------------------------------------------------

            suffix_length = (
                last_node_end
                -
                placeholder_end
            )

            if suffix_length > 0:

                suffix = last_node["text"][
                    -suffix_length:
                ]

            else:

                suffix = ""

            # --------------------------------------------------
            # Same text node.
            # --------------------------------------------------

            if first_index == last_index:

                first_node["text"] = (
                    prefix
                    +
                    replacement
                    +
                    suffix
                )

            # --------------------------------------------------
            # Placeholder spans multiple Word runs.
            # --------------------------------------------------

            else:

                first_node["text"] = (
                    prefix
                    +
                    replacement
                )

                # Empty middle nodes.
                for index in range(
                    first_index + 1,
                    last_index
                ):

                    nodes[index]["text"] = ""

                # Preserve final suffix.
                nodes[last_index]["text"] = suffix

            search_start = first_index + 1

    # ==========================================================
    # FIX BILL TABLE LAYOUT
    # ==========================================================

    def _fix_bill_table_layout(self, xml_bytes):
        """
        Find the table containing the bill placeholders and add:

            <w:tblLayout w:type="fixed"/>

        to that table's tblPr.

        This prevents the document converter from automatically
        recalculating the table's column widths after values are
        inserted.

        No rows, cells, widths, drawings or text boxes are rebuilt.
        """

        if not any(
            marker in xml_bytes
            for marker in self.BILL_PLACEHOLDER_MARKERS
        ):
            return xml_bytes

        tables = list(
            self.TBL_PATTERN.finditer(
                xml_bytes
            )
        )

        if not tables:
            return xml_bytes

        output = bytearray()

        previous_end = 0

        for table_match in tables:

            table_bytes = table_match.group(0)

            # --------------------------------------------------
            # Only target the table containing bill placeholders.
            # --------------------------------------------------

            contains_bill_placeholder = any(
                marker in table_bytes
                for marker in self.BILL_PLACEHOLDER_MARKERS
            )

            if not contains_bill_placeholder:

                continue

            # --------------------------------------------------
            # Already fixed?
            # --------------------------------------------------

            if self.TBL_LAYOUT_PATTERN.search(
                table_bytes
            ):

                continue

            # --------------------------------------------------
            # Find tblPr.
            # --------------------------------------------------

            tbl_pr_match = self.TBL_PR_PATTERN.search(
                table_bytes
            )

            if not tbl_pr_match:
                continue

            insert_position = (
                tbl_pr_match.end()
            )

            fixed_layout = (
                b'<w:tblLayout w:type="fixed"/>'
            )

            new_table = (
                table_bytes[
                    :insert_position
                ]
                +
                fixed_layout
                +
                table_bytes[
                    insert_position:
                ]
            )

            # --------------------------------------------------
            # Copy original XML before this table.
            # --------------------------------------------------

            output.extend(
                xml_bytes[
                    previous_end:
                    table_match.start()
                ]
            )

            output.extend(
                new_table
            )

            previous_end = table_match.end()

        # ------------------------------------------------------
        # If nothing was changed, return original bytes.
        # ------------------------------------------------------

        if not output:

            return xml_bytes

        output.extend(
            xml_bytes[
                previous_end:
            ]
        )

        return bytes(output)

    # ==========================================================
    # XML ESCAPING
    # ==========================================================

    def _xml_escape(self, value):

        if value is None:
            return ""

        return html.escape(
            str(value),
            quote=False
        )
