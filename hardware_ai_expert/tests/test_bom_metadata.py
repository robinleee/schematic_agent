import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware_ai_expert" / "etl_pipeline"))

from part_type_standardizer import PartTypeStandardizer


def test_bom_metadata_loaded_and_enriches_component(tmp_path):
    bom = tmp_path / "bom.csv"
    with bom.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["RefDes", "Description", "MPN", "Manufacturer", "Qty", "Package"],
        )
        writer.writeheader()
        writer.writerow({
            "RefDes": "C1,C2 R1",
            "Description": "CAP CER 10UF 16V X5R",
            "MPN": "GRM188R61C106KAALD",
            "Manufacturer": "Murata",
            "Qty": "3",
            "Package": "0603",
        })

    standardizer = PartTypeStandardizer(str(bom))

    assert standardizer.standardize("C1", "UNKNOWN_MODEL", None) == "UNKNOWN" or standardizer.get_bom_record("C1")["mpn"]
    assert standardizer.get_bom_record("C2")["manufacturer"] == "Murata"
    assert standardizer.get_bom_record("R1")["package"] == "0603"

    component = {"RefDes": "C1", "Model": "CAP_X", "PartType": "CAPACITOR"}
    enriched = standardizer.enrich_component("C1", component)
    assert enriched["MPN"] == "GRM188R61C106KAALD"
    assert enriched["Manufacturer"] == "Murata"
    assert enriched["Description"] == "CAP CER 10UF 16V X5R"
    assert enriched["Quantity"] == "3"
    assert enriched["Package"] == "0603"
