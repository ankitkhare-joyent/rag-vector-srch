from rag.search import rrf


def test_rrf_rewards_items_both_retrievers_agree_on():
    dense = ["a", "b", "c"]
    lexical = ["c", "d", "a"]
    fused = [item for item, _ in rrf([dense, lexical], k=60)]
    assert fused[0] == "a"            # rank 1 + rank 3 beats rank 1 alone
    assert set(fused) == {"a", "b", "c", "d"}


def test_rrf_scores_match_formula():
    scores = dict(rrf([["x"], ["y", "x"]], k=60))
    assert abs(scores["x"] - (1 / 61 + 1 / 62)) < 1e-12
    assert abs(scores["y"] - 1 / 61) < 1e-12
