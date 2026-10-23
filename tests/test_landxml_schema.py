from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "landxml_importer"))

from landxml import SCHEMA_GEOMETRY_ADAPTERS, parse_landxml_document, resolve_source_units  # noqa: E402


XSD_PATH = REPO_ROOT / "tests" / "fixtures" / "landxml-1.2.xsd"
XSD_SHA256 = "f4f732341970a923943f94592a3fde0838534515d564a699761e85420fad4d77"
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"


class LandXMLSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema_root = ET.parse(XSD_PATH).getroot()
        cls.elements = {
            element.get("name")
            for element in cls.schema_root.iter(f"{{{XSD_NAMESPACE}}}element")
            if element.get("name")
        }
        cls.attributes = {
            attribute.get("name")
            for attribute in cls.schema_root.iter(f"{{{XSD_NAMESPACE}}}attribute")
            if attribute.get("name")
        }

    def test_pinned_schema_checksum_and_declaration_counts(self):
        self.assertEqual(hashlib.sha256(XSD_PATH.read_bytes()).hexdigest(), XSD_SHA256)
        self.assertGreaterEqual(len(self.elements), 200)
        self.assertGreaterEqual(len(self.attributes), 450)

    def test_specialized_adapters_are_declared_in_the_schema(self):
        self.assertTrue(set(SCHEMA_GEOMETRY_ADAPTERS).issubset(self.elements))

    def test_linear_unit_enumerations_resolve(self):
        linear_units = set()
        for type_name in ("metLinear", "impLinear"):
            unit_type = self.schema_root.find(f"{{{XSD_NAMESPACE}}}simpleType[@name='{type_name}']")
            linear_units.update(
                value.get("value")
                for value in unit_type.iter(f"{{{XSD_NAMESPACE}}}enumeration")
            )
        self.assertEqual(
            linear_units,
            {"millimeter", "centimeter", "meter", "kilometer", "foot", "USSurveyFoot", "inch", "mile"},
        )
        for unit in linear_units:
            with self.subTest(unit=unit):
                self.assertIsNotNone(resolve_source_units(unit)[0])

    def test_unadapted_standard_records_are_preserved_generically(self):
        unknown_standard_name = next(
            name for name in sorted(self.elements)
            if name not in SCHEMA_GEOMETRY_ADAPTERS and name not in {"LandXML", "Units"}
        )
        document_text = (
            f"<LandXML><Project name='Test'><{unknown_standard_name} custom='kept'>  value \n</{unknown_standard_name}>"
            "  mixed tail  </Project></LandXML>"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as file:
            file.write(document_text)
            path = Path(file.name)
        try:
            document = parse_landxml_document(path)
        finally:
            path.unlink()

        project = next(child for child in document.root.children if child.name == "Project")
        record = project.children[0]
        self.assertEqual(record.name, unknown_standard_name)
        self.assertEqual(dict(record.attributes), {"custom": "kept"})
        self.assertEqual(record.text, "  value \n")
        self.assertEqual(record.tail, "  mixed tail  ")


if __name__ == "__main__":
    unittest.main()