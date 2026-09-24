"""
test_mrz.py - Unit tests for ICAO 9303 MRZ parsing and checksum verification.
"""
import pytest
from backend.modules.ocr_extraction.mrz_parser import _icao_checksum, validate_checksum, _parse_td3, parse_mrz


def test_icao_checksum_algorithm():
    # Standard ICAO 9303 test vector:
    # "L898902C<" -> check digit is 3
    doc_num = "L898902C<"
    assert _icao_checksum(doc_num) == 3
    assert validate_checksum(doc_num, "3") is True
    assert validate_checksum(doc_num, "4") is False


def test_passport_td3_mrz_valid():
    # Standard valid 2-line TD3 passport MRZ
    line1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
    line2 = "L898902C<3UTO6908061F9406236ZE184226B<<<<<14"
    
    mrz = _parse_td3(line1, line2)
    assert mrz.doc_type == "P"
    assert mrz.country == "UTO"
    assert mrz.surname == "ERIKSSON"
    assert mrz.given_names == "ANNA MARIA"
    assert mrz.doc_number == "L898902C"
    assert mrz.nationality == "UTO"
    assert mrz.dob == "690806"
    assert mrz.sex == "F"
    assert mrz.expiry == "940623"
    assert mrz.all_valid is True
    assert mrz.checksums_ok.get("doc_number") is True
    assert mrz.checksums_ok.get("dob") is True
    assert mrz.checksums_ok.get("expiry") is True


def test_passport_td3_tampered_checksum():
    # Tampered MRZ: corrupted birth date checksum digit (changed 1 to 9)
    line1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
    line2 = "L898902C<3UTO6908069F9406236ZE184226B<<<<<14"
    
    mrz = _parse_td3(line1, line2)
    assert mrz.all_valid is False
    assert mrz.checksums_ok.get("dob") is False
