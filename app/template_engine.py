from pathlib import Path
import html
import re
import zipfile


class TemplateEngine:
    """
    Surgical DOCX template renderer.

    IMPORTANT:
    This renderer deliberately does NOT use python-docx or lxml.

    It preserves the original DOCX XML structure and changes only
    the text contained inside <w:t> elements.

    This is important for templates containing floating text boxes,
    drawings, images, signatures, and positioned shapes.
    """

    TEXT_TAG_PATTERN = re.compile(
        rb"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)",
        re.DOTALL,
    )

    PLACEHOLDER_PATTERN = re.compile(
        r"\{\{[^{}]+\}\}"
    )

    def __init__(self):
        self.missing_placeholders = set()

    # ==========================================================
    # PUBLIC METHOD
    # ==========================================================

    def render(self, template_path, output_path, data):
        """
        Render a DOCX template.

        Existing integration:

            TemplateEngine().render(
                template_path,
                output_path,
                data
            )

        Returns:
            sorted list of missing placeholders
        """

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

                    # Only process Word XML.
                    #
                    # Do NOT touch:
                    # - images
                    # - relationships
                    # - settings
                    # - styles
                    # - numbering
                    # - document properties
                    # - media
                    # - embedded objects
                    #
                    if self._is_word_xml(item.filename):

                        content = self._replace_in_xml(
                            content,
                            replacements
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

            # --------------------------------------------------
            # Accept:
            #
            # LG_CODE
            # {{LG_CODE}}
            # --------------------------------------------------

            if (
                key.startswith("{{")
                and
                key.endswith("}}")
            ):
                placeholder = key
            else:
                placeholder = "{{" + key + "}}"

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

        # Preserve ordinary strings exactly.
        if isinstance(value, str):
            return value

        # Excel numeric values.
        #
        # Avoid displaying:
        # 60000.0
        #
        # when the value is effectively an integer.
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

        if not filename.startswith("word/"):
            return False

        if not filename.endswith(".xml"):
            return False

        return True

    # ==========================================================
    # XML PROCESSING
    # ==========================================================

    def _replace_in_xml(
        self,
        xml_bytes,
        replacements
    ):
        """
        Replace placeholders without rebuilding the XML tree.

        Only the contents of <w:t> elements are changed.
        All XML structure, attributes, shapes, tables, drawings,
        positioning information and other document content remain
        untouched.
        """

        matches = list(
            self.TEXT_TAG_PATTERN.finditer(
                xml_bytes
            )
        )

        if not matches:
            return xml_bytes

        # ------------------------------------------------------
        # Extract the original text-node contents.
        # ------------------------------------------------------

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
        # Process every placeholder.
        # ------------------------------------------------------

        for placeholder, replacement in replacements.items():

            self._replace_placeholder_across_nodes(
                nodes,
                placeholder,
                replacement
            )

        # ------------------------------------------------------
        # Reconstruct the ORIGINAL XML bytes.
        #
        # Only w:t contents are replaced.
        # Everything between those text nodes is copied directly
        # from the original XML.
        # ------------------------------------------------------

        output = bytearray()

        previous_end = 0

        for index, match in enumerate(matches):

            node = nodes[index]

            # Original XML before this text body.
            output.extend(
                xml_bytes[
                    previous_end:
                    match.start(2)
                ]
            )

            new_text = self._xml_escape(
                node["text"]
            )

            output.extend(
                new_text.encode(
                    "utf-8"
                )
            )

            previous_end = match.end(2)

        # Remaining original XML.
        output.extend(
            xml_bytes[
                previous_end:
            ]
        )

        return bytes(output)

    # ==========================================================
    # PLACEHOLDER REPLACEMENT
    # ==========================================================

    def _replace_placeholder_across_nodes(
        self,
        nodes,
        placeholder,
        replacement
    ):
        """
        Replace a placeholder even when Word has split it across
        multiple runs/text nodes.

        Example:

            <w:t>{{LG_</w:t>
            <w:t>CODE}}</w:t>

        becomes:

            <w:t>GUS-12345678</w:t>
            <w:t></w:t>

        The surrounding XML remains untouched.
        """

        if not placeholder:
            return

        # ------------------------------------------------------
        # We may need to replace the same placeholder more than
        # once in the document.
        # ------------------------------------------------------

        search_start = 0

        while search_start < len(nodes):

            combined = ""
            mapping = []

            found = False

            # --------------------------------------------------
            # Build text progressively from the current node.
            # --------------------------------------------------

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

                # Prevent unlimited accumulation where possible.
                #
                # A placeholder is short, so once the accumulated
                # text becomes large and the placeholder cannot
                # possibly cross the boundary, we can still
                # continue normally.
                #
                # No structural document changes occur here.

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

            # --------------------------------------------------
            # Identify the text nodes containing the placeholder.
            # --------------------------------------------------

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
            # Prefix before placeholder.
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
            # Suffix after placeholder.
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
            # Replacement.
            # --------------------------------------------------

            if first_index == last_index:

                first_node["text"] = (
                    prefix
                    +
                    replacement
                    +
                    suffix
                )

            else:

                first_node["text"] = (
                    prefix
                    +
                    replacement
                )

                # Empty the nodes between first and last.
                for index in range(
                    first_index + 1,
                    last_index
                ):
                    nodes[index]["text"] = ""

                # Preserve the suffix in the final node.
                nodes[last_index]["text"] = suffix

            # --------------------------------------------------
            # This placeholder has now been replaced.
            # Continue searching after the first affected node.
            # --------------------------------------------------

            search_start = first_index + 1

        # ------------------------------------------------------
        # Verify whether this placeholder still exists.
        # ------------------------------------------------------

        remaining = "".join(
            node["text"]
            for node in nodes
        )

        if placeholder in remaining:

            self.missing_placeholders.add(
                placeholder
            )

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
