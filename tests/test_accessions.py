from autobiosci_sentinel.accessions import describe_accession, extract_accessions


def test_extract_accessions_unique_sorted():
    text = "GSE123 and gse123 plus SRR456, PRJNA789, E-MTAB-111 and ERR22."

    assert extract_accessions(text) == ["E-MTAB-111", "ERR22", "GSE123", "PRJNA789", "SRR456"]


def test_describe_accession_known_sources():
    assert describe_accession("gse123") == {
        "accession": "GSE123",
        "source": "GEO",
        "url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123",
    }
    assert describe_accession("SRR456")["source"] == "SRA"
    assert describe_accession("PRJNA789")["source"] == "BioProject"
    assert describe_accession("ERR22")["source"] == "ENA"
    assert describe_accession("E-MTAB-111")["source"] == "ArrayExpress"
