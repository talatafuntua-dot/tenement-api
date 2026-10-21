from pathlib import Path
import html
import re
import zipfile


class TemplateEngine:
    """
    Replace {{PLACEHOLDER}} values in a DOCX while preserving unrelated
    Word XML content. This version deliberately does not alter table layout.

    Note: Word can split a placeholder across multiple runs/text nodes.
    This engine supports placeholders split across adjacent <w:t> nodes
    within the same XML file.
    """

    TEXT_TAG_PATTERN = re.compile(
        rb"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)",
        re.DOTALL,
    )

    def __init__(self):
        self.missing_placeholders = []

    def render(self, template_path, output_path, data):
        template_path = Path(template_path)
        output_path = Path(output_path)

        if not template_path.exists():
            raise FileNotFoundError(f"Word template not found: {template_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        replacements = self._build_replacements(data)
        self.missing_placeholders = []

        with zipfile.ZipFile(template_path, "r") as source_zip:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    content = source_zip.read(item.filename)

                    if (
                        item.filename.startswith("word/")
                        and item.filename.endswith(".xml")
                    ):
                        content = self._replace_in_xml(content, replacements)

                    output_zip.writestr(item, content)

        return {
            "output_path": str(output_path),
            "replacements_count": len(replacements),
            "missing_placeholders": self.missing_placeholders,
        }

    def _build_replacements(self, data):
        replacements = {}

        if not data:
            return replacements

        for key, value in data.items():
            if key is None:
                continue

            key_text = str(key).strip()
            if not key_text:
                continue

            placeholder = key_text
            if not (placeholder.startswith("{{") and placeholder.endswith("}}")):
                placeholder = "{{" + placeholder.strip("{} ").upper() + "}}"

            if value is None:
                replacement = ""
            else:
                replacement = self._format_value(value)

            replacements[placeholder] = replacement

        # Longer keys first, in case placeholder names overlap.
        return dict(
            sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True)
        )

    @staticmethod
    def _format_value(value):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _replace_in_xml(self, xml_content, replacements):
        matches = list(self.TEXT_TAG_PATTERN.finditer(xml_content))
        if not matches or not replacements:
            return xml_content

        nodes = []
        for match in matches:
            raw_inner = match.group(2)

            try:
                decoded = raw_inner.decode("utf-8")
                logical_text = html.unescape(decoded)
            except UnicodeDecodeError:
                # Leave malformed/unexpected text untouched.
                logical_text = None

            nodes.append(
                {
                    "start": match.start(2),
                    "end": match.end(2),
                    "raw": raw_inner,
                    "text": logical_text,
                    "changed": False,
                }
            )

        # Apply each placeholder to the combined logical text across all
        # text nodes. Replacements only modify nodes containing a match.
        for placeholder, replacement in replacements.items():
            self._replace_placeholder_across_nodes(nodes, placeholder, replacement)

        # Rebuild only the inner contents of text nodes that actually changed.
        # All unchanged text nodes and all other XML bytes remain untouched.
        result = bytearray()
        cursor = 0

        for node in nodes:
            result.extend(xml_content[cursor:node["start"]])

            if node["changed"]:
                escaped = html.escape(node["text"], quote=False).encode("utf-8")
                result.extend(escaped)
            else:
                result.extend(node["raw"])

            cursor = node["end"]

        result.extend(xml_content[cursor:])
        return bytes(result)

    @staticmethod
    def _replace_placeholder_across_nodes(nodes, placeholder, replacement):
        if not nodes:
            return

        # If any text node could not be decoded, exclude it from cross-node
        # matching rather than risk corrupting its XML.
        valid_nodes = [node for node in nodes if node["text"] is not None]
        if not valid_nodes:
            return

        while True:
            combined_parts = []
            ranges = []
            position = 0

            for node in valid_nodes:
                text_value = node["text"]
                start = position
                position += len(text_value)
                ranges.append((start, position, node))
                combined_parts.append(text_value)

            combined = "".join(combined_parts)
            found_at = combined.find(placeholder)
            if found_at < 0:
                break

            found_end = found_at + len(placeholder)
            first_node = None
            last_node = None
            first_local = 0
            last_local_end = 0

            for start, end, node in ranges:
                if first_node is None and start <= found_at < end:
                    first_node = node
                    first_local = found_at - start

                if start < found_end <= end:
                    last_node = node
                    last_local_end = found_end - start
                    break

                # A match can end exactly at a node boundary.
                if found_end == start:
                    last_node = valid_nodes[ranges.index((start, end, node)) - 1] if start else node
                    if last_node is not node:
                        previous_text = last_node["text"]
                        last_local_end = len(previous_text)
                    else:
                        last_local_end = 0
                    break

            if first_node is None or last_node is None:
                break

            if first_node is last_node:
                original = first_node["text"]
                first_node["text"] = (
                    original[:first_local]
                    + replacement
                    + original[last_local_end:]
                )
                first_node["changed"] = True
            else:
                first_original = first_node["text"]
                last_original = last_node["text"]

                first_node["text"] = first_original[:first_local] + replacement
                first_node["changed"] = True

                started = False
                for node in valid_nodes:
                    if node is first_node:
                        started = True
                        continue
                    if node is last_node:
                        node["text"] = last_original[last_local_end:]
                        node["changed"] = True
                        break
                    if started:
                        node["text"] = ""
                        node["changed"] = True

            # Continue from the updated node texts. If replacement is empty,
            # the next iteration still finds any later occurrence.
