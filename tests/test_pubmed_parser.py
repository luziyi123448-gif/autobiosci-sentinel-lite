from autobiosci_sentinel import pubmed
from autobiosci_sentinel.pubmed import parse_pubmed_xml


def test_parse_pubmed_xml_core_fields():
    xml = """
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>12345</PMID>
          <Article>
            <ArticleTitle>Cancer <i>RNA-seq</i> study</ArticleTitle>
            <Abstract>
              <AbstractText>First abstract sentence.</AbstractText>
              <AbstractText Label="Results">Nested <b>text</b> is preserved.</AbstractText>
            </Abstract>
            <Journal>
              <Title>Journal of Tests</Title>
              <JournalIssue>
                <PubDate><Year>2026</Year><Month>Jul</Month><Day>02</Day></PubDate>
              </JournalIssue>
            </Journal>
            <AuthorList>
              <Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author>
            </AuthorList>
          </Article>
        </MedlineCitation>
        <PubmedData>
          <ArticleIdList><ArticleId IdType="doi">10.1000/test</ArticleId></ArticleIdList>
        </PubmedData>
      </PubmedArticle>
    </PubmedArticleSet>
    """

    papers = parse_pubmed_xml(xml, "topic", fetched_at="2026-07-04T00:00:00Z")

    assert len(papers) == 1
    paper = papers[0]
    assert paper["pmid"] == "12345"
    assert paper["title"] == "Cancer RNA-seq study"
    assert "Nested text is preserved." in paper["abstract"]
    assert paper["journal"] == "Journal of Tests"
    assert paper["pub_date"] == "2026-07-02"
    assert paper["authors"] == "Ada Lovelace"
    assert paper["doi"] == "10.1000/test"


def test_search_pubmed_adds_publication_date_range(monkeypatch):
    captured = {}

    def fake_get_json(url, params):
        captured["url"] = url
        captured["params"] = params
        return {"esearchresult": {"idlist": ["12345"]}}

    monkeypatch.setattr(pubmed, "_get_json", fake_get_json)

    ids = pubmed.search_pubmed(
        "cancer",
        10,
        days_back=30,
        start_date="2026/01/01",
        end_date="2026/07/01",
    )

    assert ids == ["12345"]
    assert captured["url"] == pubmed.ESEARCH_URL
    assert captured["params"] == {
        "db": "pubmed",
        "term": "cancer",
        "retmode": "json",
        "sort": "pub+date",
        "retmax": 10,
        "datetype": "pdat",
        "mindate": "2026/01/01",
        "maxdate": "2026/07/01",
    }


def test_search_pubmed_keeps_raw_count(monkeypatch):
    monkeypatch.setattr(
        pubmed,
        "_get_json",
        lambda url, params: {"esearchresult": {"count": "123", "idlist": ["12345"]}},
    )

    ids = pubmed.search_pubmed("cancer", 10)

    assert ids == ["12345"]
    assert ids.raw_count == 123


def test_search_pubmed_adds_retstart(monkeypatch):
    captured = {}

    def fake_get_json(url, params):
        captured["params"] = params
        return {"esearchresult": {"count": "20", "idlist": ["2"]}}

    monkeypatch.setattr(pubmed, "_get_json", fake_get_json)

    ids = pubmed.search_pubmed("cancer", 10, retstart=10)

    assert ids == ["2"]
    assert captured["params"]["retstart"] == 10


def test_search_pubmed_all_pmids_paginates(monkeypatch):
    calls = []

    def fake_get_json(url, params):
        calls.append(dict(params))
        pages = {
            0: ["1", "2"],
            2: ["3", "4"],
            4: ["5"],
        }
        return {"esearchresult": {"count": "5", "idlist": pages.get(params.get("retstart", 0), [])}}

    monkeypatch.setattr(pubmed, "_get_json", fake_get_json)

    ids = pubmed.search_pubmed_all_pmids("cancer", batch_size=2)

    assert ids == ["1", "2", "3", "4", "5"]
    assert ids.raw_count == 5
    assert [call.get("retstart", 0) for call in calls] == [0, 2, 4]
