"""Extract PaperCard for arXiv 2301.13410 using LLM."""
import json
import re
import sys

sys.path.insert(0, "packages/paperindex")
from paperindex.llm.client import LLMClient, resolve_llm_config

PAPER_TEXT = """
Title: Multi-Channel Auction Design in the Autobidding World
Authors: Gagan Aggarwal, Andres Perlroth, Junyao Zhao
Date: February 1, 2023
arXiv: 2301.13410

Abstract:
Over the past few years, more and more Internet advertisers have started using automated bidding for optimizing their advertising campaigns. Such advertisers have an optimization goal (e.g. to maximize conversions), and some constraints (e.g. a budget or an upper bound on average cost per conversion), and the automated bidding system optimizes their auction bids on their behalf. Often, these advertisers participate on multiple advertising channels and try to optimize across these channels. A central question that remains unexplored is how automated bidding affects optimal auction design in the multi-channel setting.

In this paper, we study the problem of setting auction reserve prices in the multi-channel setting. In particular, we shed light on the revenue implications of whether each channel optimizes its reserve price locally, or whether the channels optimize them globally to maximize total revenue. Motivated by practice, we consider two models: one in which the channels have full freedom to set reserve prices, and another in which the channels have to respect floor prices set by the publisher. We show that in the first model, welfare and revenue loss from local optimization is bounded by a function of the advertisers inputs, but is independent of the number of channels and bidders. In stark contrast, we show that the revenue from local optimization could be arbitrarily smaller than those from global optimization in the second model.

1 Introduction:
Advertisers are increasingly using automated bidding in order to set bids for ad auctions in online advertising. Automated bidding simplifies the bidding process for advertisers - it allows an advertiser to specify a high-level goal and one or more constraints, and optimizes their auction bids on their behalf. Common goals include maximize conversions or conversion value. Common constraints include Budgets and TargetCPA (upper bound on average cost per conversion).

One central question that remains unexplored is how automated bidding affects optimal auction design in the multi-channel setting. It is common for advertisers to show ads on multiple channels and optimize across channels. For example, an advertiser can optimize across Google Ads inventory (YouTube, Display, Search, Discover, Gmail, Maps) with Performance Ads, or can optimize across Facebook, Instagram and Messenger with Automated Ad Placement.

With traditional quasi-linear bidders, the problem of auction design on each channel is independent of other channels designs. However, when advertisers use automated bidders and optimize across channels, the auction design of one channel creates externalities for the other channels through the constraints of automated bidders.

The paper introduces the problem of auction design in the multi-channel setting with automated bidding across channels. In particular, it studies the problem of setting reserve prices across channels with two behavior models: Local and Global. In the Local model, each channel optimizes its reserve price to maximize its own revenue. In the Global model, channels optimize their reserve prices globally to maximize total revenue across channels.

Two settings are considered: Without Publisher Reserves (channels have full control over reserve prices) and With Publisher Reserves (channels must respect externally-imposed lower bounds on reserve prices).

Model:
The model consists of k channels, each selling a set of impressions. Each channel can set a uniform reserve price in cost-per-unit-value space. Impressions are sold in Second-Price-Auctions with floor prices. Bidders want to maximize conversions subject to constraints: (1) Budget, (2) TargetCPA, or (3) Quasi-linear (no constraint).

The game is a two-stage game: First, each channel simultaneously announces its reserve price; then, bidders bid optimally for different impressions. Bidders use uniform bidding (bidding parameter alpha_j such that b_{j,i} = alpha_j * v_{j,i}).

Key Results:

1. Hardness of Equilibrium Computation (Theorem 1): Finding the subgame equilibrium is PPAD-hard. Proved by reduction from finding approximate Nash equilibrium for 0-1 bimatrix game.

2. Setting Without Publisher Reserves:
- Revenue Guarantee (Theorem 2): Revenue guarantee in the local model is at least Omega(1/log(eta)) of the optimal Liquid Welfare, where eta depends on bidders inputs and quantifies the heterogeneity of the pool of bidders (eta = max of ratio of highest to lowest TargetCPA among tCPA bidders and a similar ratio for Budgeted bidders).
- Tightness (Proposition 3): This bound is tight up to constant factors even in the single-channel setting.
- Price of Anarchy (Theorem 5): PoA = Theta(1/(log(T_max/T_min) + log(beta_max/beta_min))). The revenue gap is independent of the number of channels and bidders.

3. Setting With Publisher Reserves:
- General Channels (Theorem 6): PoA = 0 in the worst case - revenue from local optimization can be arbitrarily smaller than global optimization.
- Scaled Channels with multiple bidders (Theorem 7): PoA = 0 in worst case even for scaled channels with 2+ bidders.
- Scaled Channels with one bidder (Theorem 8): PoA = 1/|K| where K is the number of channels.

Key concepts: Liquid Welfare (Definition 2), Budget-fraction (Definition 5), Subgame Bidding Equilibrium (Definition 1), Price of Anarchy (Definition 4).

Related Work:
- Autobidding: Aggarwal et al. 2019 (initiate study of autobidding), Deng et al. 2021 (boosts for welfare), Balseiro et al. 2021 (revenue-optimal auctions, reserve prices with autobidders) - all in single-channel setting.
- Multi-channel auction design: Burguet & Sakovics 1999, Ellison et al. 2004 - competition across channels with captive buyers. This paper differs: bidders are not captive but optimize under autobidding constraints.

Further Discussion:
- Results extend to welfare bounds (similar to revenue bounds).
- Results can be adapted to cost-per-impression reserve prices (value-independent).
- Interesting phenomenon: in autobidding, higher reserve prices can sometimes increase welfare (contrast with quasi-linear setting).
"""

PROMPT = f"""You are an academic paper analysis assistant. Extract a structured paper card from the following paper content. Return ONLY a JSON object (no markdown fences, no explanation) with these fields:

- title, authors (list of strings), venue (string), year (string)
- core_idea: 1-3 sentences summarizing the key insight
- motivation: why this problem matters
- problem_definition: formal problem statement
- method_summary: 2-4 sentences describing the approach
- method_pipeline: list of ordered steps
- method_family: one of ["learning_based", "optimization_based", "probabilistic", "game_theoretic", "heuristic"]
- method_tags: list of specific techniques
- algorithmic_view: pseudocode-level description
- contributions: list of claimed contributions
- related_work_positioning: how it positions vs prior work
- key_references: list of important cited works (author year title)
- assumptions: list
- limitations: list
- future_directions: string
- tasks: list
- datasets: list
- metrics: list
- baselines: list
- key_results: list of main findings
- ablation_focus: list of what ablations study
- domain_tags: list
- technical_tags: list
- code_url: string or null
- reproducibility_score: one of ["high", "medium", "low", "unknown"]
- reproduction_notes: string or null

Paper content:
{PAPER_TEXT}
"""

if __name__ == "__main__":
    config = resolve_llm_config()
    print(f"Using provider: {config.provider}, model: {config.model}", file=sys.stderr)
    client = LLMClient(config)
    raw = client.chat(PROMPT)
    print(f"Raw response length: {len(raw)}", file=sys.stderr)

    # Try to parse JSON
    json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if json_match:
        card_data = json.loads(json_match.group(1))
    else:
        # Try direct JSON parse
        card_data = json.loads(raw.strip())

    with open("paper_library/papers/card_2301.13410.json", "w") as f:
        json.dump(card_data, f, indent=2, ensure_ascii=False)

    print(json.dumps(card_data, indent=2, ensure_ascii=False)[:3000])
