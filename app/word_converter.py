# -*- coding: utf-8 -*-
"""
word_converter.py
Microsoft Word PDF Converter

Uses Microsoft Word COM automation to convert DOCX files
to high-quality PDFs.

Features
--------
✓ Single Word session
✓ Fast batch conversion
✓ Automatic cleanup
✓ Proper exception handling
✓ Optional visible Word window
"""

import os
import pythoncom
import win32com.client

from app.config import WORD_PDF_FORMAT, SHOW_WORD


class WordConverter:
    """
    Maintains one Microsoft Word session for all conversions.
    """

    def __init__(self):

        self.word = None

    # ---------------------------------------------------
    # Context Manager Support
    # ---------------------------------------------------

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    # ---------------------------------------------------
    # Start Microsoft Word
    # ---------------------------------------------------

    def start(self):

        if self.word is not None:
            return

        pythoncom.CoInitialize()

        self.word = win32com.client.DispatchEx("Word.Application")

        self.word.Visible = SHOW_WORD

        self.word.DisplayAlerts = False

    # ---------------------------------------------------
    # Convert One File
    # ---------------------------------------------------

    def convert(self, docx_path, pdf_path):
        """
        Convert DOCX to PDF.

        Returns
        -------
        (success, message)
        """

        if not os.path.exists(docx_path):
            return False, f"Document not found:\n{docx_path}"

        document = None

        try:

            document = self.word.Documents.Open(
                os.path.abspath(docx_path),
                ReadOnly=True
            )

            document.SaveAs(
                os.path.abspath(pdf_path),
                FileFormat=WORD_PDF_FORMAT
            )

            document.Close(False)

            return True, "OK"

        except Exception as ex:

            try:
                if document:
                    document.Close(False)
            except Exception:
                pass

            return False, str(ex)

    # ---------------------------------------------------
    # Batch Convert
    # ---------------------------------------------------

    def convert_many(self, jobs):
        """
        jobs =

        [
            (doc1, pdf1),
            (doc2, pdf2)
        ]

        Returns

        [
            (True,"OK"),
            (False,"reason")
        ]
        """

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
    # Close Word
    # ---------------------------------------------------

    def close(self):

        if self.word is None:
            return

        try:
            self.word.Quit()
        except Exception:
            pass

        self.word = None

        pythoncom.CoUninitialize()