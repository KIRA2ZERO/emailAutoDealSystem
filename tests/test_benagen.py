import unittest

from processors.benagen.module import (
    existBenagenData,
    extract_download_urls,
    parseBenagenData,
)


PAGE_URL = (
    "http://download.benagen.com/token/"
    "23268-JKXD20260716-083855-5BQ6TY-BN260628GZ01S37N3.html"
)


class BenagenProcessorTest(unittest.TestCase):
    def test_recognizes_and_parses_delivery_page(self):
        body = f'<a href="{PAGE_URL}">download</a>'
        self.assertTrue(existBenagenData(body))
        self.assertEqual(parseBenagenData(body), {"page_urls": [PAGE_URL]})

    def test_decodes_html_escaped_query_string(self):
        url = PAGE_URL + "?a=1&b=2"
        self.assertEqual(
            parseBenagenData(url.replace("&", "&amp;")),
            {"page_urls": [url]},
        )

    def test_extracts_only_benagen_data_urls(self):
        page_html = f"""
            <input data-url="file_000.zip">
            <input data-url="http://download.benagen.com/token/check.md5">
            <input data-url="https://example.com/unrelated.zip">
            <a href="https://www.xunlei.com/">tool</a>
            <input data-url="{PAGE_URL}">
            <input data-url="file_000.zip">
        """
        self.assertEqual(
            extract_download_urls(page_html, PAGE_URL),
            [
                "http://download.benagen.com/token/file_000.zip",
                "http://download.benagen.com/token/check.md5",
            ],
        )


if __name__ == "__main__":
    unittest.main()
