#!/usr/bin/env python3
"""Extract PaperCard for arXiv:2305.06883 using LLM client."""

import json
import re
import sys

sys.path.insert(0, "packages/paperindex")
from paperindex.llm.client import LLMClient, resolve_llm_config

PAPER_TEXT = """Cross-channel Budget Coordination for Online Advertising System

Authors: Guangyuan Shen, Shenjie Sun, Dehong Gao, Shaolei Li, Libin Yang, Yongping Shi, Wei Ning
Affiliation: Alibaba Group, Hangzhou, Zhejiang, China

ABSTRACT
In online advertising (Ad), advertisers are always eager to know how to globally optimize their budget allocation strategies across different channels for more conversions such as orders, payments, etc. Ignoring competition among different advertisers causes objective inconsistency, that is, a single advertiser locally optimizes the conversions only based on its own historical statistics, which is far behind the global conversions maximization. In this paper, we present a cross-channel Advertising Coordinated budget allocation framework (AdCob) to globally optimize the budget allocation strategy for overall conversions maximization. We are the first to provide deep insight into modeling the competition among different advertisers in cross-channel budget allocation problems. The proposed iterative algorithm combined with entropy constraint is fast to converge and easy to implement in large-scale online Ad systems. Both results from offline experiments and online A/B budget bucketing experiments demonstrate the effectiveness of AdCob.

KEYWORDS: Online Advertising, Budget, Cross-channel Budget Management

1 INTRODUCTION
Budget management is essential for e-commerce search Advertising (Ad) systems, which simultaneously and deeply impacts the revenues of platforms and the performances of the advertisers. The overall traffic is composed of different channels according to the Ad display-ends such as mobile, laptop, etc. If advertisers do not heuristically distribute their budgets, the Ad systems will roughly apply a first-come-first-served strategy. Under this situation, a first-come channel with poor quality may preempt the budgets of late-come channels with better quality, which leads to a conversions decrease within limited budgets. Advertisers are thus eager to know how to reasonably distribute their limited budgets across different channels to obtain more conversions.

There is indeed some research working on optimizing the cross-channel budget allocation strategy for a single advertiser. They assume that all the other advertisers are stationary, that is, maintaining their original allocation strategy. These works focus on one advertiser and optimize one own conversions only based on local historical statistics. None of them provide insights into modeling the competition among different advertisers. Ignoring this competition causes objective inconsistency, that is, the Ad system is in a state of imperfect information competition. We argue that under this situation, the Ad system will converge to a local optimal point of an inconsistent objective. The local optimal point can be arbitrarily different from the global objective depending upon the proportion of advertisers adopting a greedy allocation strategy. Specifically, if most advertisers greedily allocate their budgets to a small number of channels that they prefer, this will lead to such channels being allocated excessive budgets which may be beyond the upper bound that these channels can handle, i.e., excessive competition. Such excessive competition not only leads to increasing costs for advertisers who have won the exposure opportunities in such channels but also lose potential exposure chances in other channels.

In this paper, we focus on the prosperity of the market, coordinating all advertisers to optimize the global budget strategy across different channels for overall conversion maximization while maintaining platform revenue as much as possible. To solve this problem, we cast the overall budget allocation problem as an Optimal Transport (OT) problem and propose Advertising Coordinated budget allocation (AdCob) approach, which satisfies the constraints of the advertiser budgets and the channels cost upper limits at the same time. Based on the cost matrix, AdCob transfers advertisers budgets to different channels with minimal conversion cost under bilateral constraints, which is more in line with the global optimal objective, i.e., global conversion maximization. Almost all the advertisers can enjoy a better utility as the unreasonable competition (both excess and lack) is mitigated. With a controllable entropy variable, AdCob largely enhances objective consistency while preserving high search efficiency by searching space reduction.

Our main contributions are summarized below:
- We propose the global cross-channel budget allocation and cast it as Optimal Transport, which provides the first insight into modeling the competition among different advertisers and coordinating their budgets.
- We employ the iterative algorithm with entropy constraint which accelerates the training convergence and ensures large-scale implementation. Thanks to its simple framework, AdCob can be easily deployed to other Ad systems with cross-channel budget management needs.
- We have deployed the AdCob framework in an online advertising system. The results from the offline experiments and the online A/B budget-bucketing experiments demonstrate the effectiveness of our proposed approach.

2 RELATED WORK
A recent strand of literature has considered different aspects of budget management in cross-channel Ad auctions. The main difference to our work is that these works focus on a single advertiser, which is different from our global advertiser coordination.

Earlier literature introduces the Multiple-Choice Knapsack (MCK) model to solve the cross-channel budget allocation of one single advertiser. Some researchers take traffic fluctuations caused by time into consideration, and they cast the time-considered allocation as a reinforcement learning-based MCK problem. On this basis, the interactions among sub-campaigns are modeled in the allocation model. All these methods ignore the interactions among a tremendous number of advertisers, that is, only working under the assumption that all the other advertisers keep the static strategy. These methods seem not suitable for real online Ad systems where millions of users bid to show their ads.

Besides, pacing methods are another series of budget management focusing on how to allocate the budget over the time blocks of a channel or how to adjust the budget cost rate according to the budget usage. Pacing methods can also be regarded as cross-channel budget allocation by distributing the budgets across different time segmentations (channels).

3 METHOD

3.1 Optimal Transport Problem
Optimal transport (OT) is the problem of moving goods from one set of warehouses to another set of destinations while minimizing certain cost functions. Suppose that we have N warehouses, the number of goods in each warehouse is {G_i}, and need to be moved to M different places. The quantity of demanded goods of each destination is {D_j}, and the unit transportation cost between the i-th warehouse and the j-th destination constructs the cost matrix C = {c(x_i, y_j)}. The OT problem minimizes the total transportation cost subject to supply and demand constraints. If we are in the unbalance situation where sum(G_i) <= sum(D_j), we can set a virtual warehouse to bridge the gap with zero cost.

3.2 Budget Allocation via Optimal Transport
In an online Ad system, advertisers are allowed to create Ad campaigns and the budget allocation refers to the budget allocation of each campaign. We reformulate the global cross-channel budget allocation as an unbalanced OT. Campaigns budgets are viewed as the goods in warehouses while the channel cost upper limits are viewed as the demanded goods at each destination.

Suppose we have N Ad campaigns with budgets b := {b_i}, and have M channels with different daily cost upper limits h := {h_j}. We try to maximize the number of conversions by optimizing the budget allocation matrix P := {P_{i,j}}, where P_{i,j} denotes the budget that the i-th campaign distributes to the j-th channel. When the total budget is fixed, the objective converts to minimize the global CPC (Cost Per Conversion), i.e., minimize the linear combination of different CPC_{i,j} with weight P_{i,j}. Here C := {CPC_{i,j}} denotes the CPC of the i-th campaign on the j-th channel.

In practice, the sum of the cost upper limits of all channels is always greater than the sum of all the budgets. We make up a virtual campaign with virtual budget to bridge the budget gap and simply set its CPC on each channel as 0. This is a large-scale linear programming problem with tremendous numbers of constraints. The complexity of the greedy solution is O(N^3 log N), the iteration speed is too slow.

3.3 Iterative Solution with Entropy Constraint
The problem can be solved in a practical and scalable way by adding an entropy penalty and using the matrix scaling Sinkhorn algorithm. The new objective adds -epsilon * H(P) where H(P) is the entropy of the allocation matrix. Since the objective is epsilon-strongly convex, it has a unique optimal solution. Introducing dual variables f and g for each marginal constraint, the Lagrangian yields the optimal coupling P_{i,j} = exp(f_i/epsilon) * exp(-C_{i,j}/epsilon) * exp(g_j/epsilon). We iterate over {f_l} and {g_l} using Sinkhorn iterations until convergence. The sequences essentially represent how the solution satisfies the bilateral constraints. We alternately satisfy the campaigns budget constraints and channel cost upper limit constraints.

The epsilon controls the strength of the regularization. As epsilon goes to zero, more accurate solutions can be obtained while the campaigns budget will be centrally allocated to certain channels bringing numerical instability.

4 IMPLEMENTATION DETAILS

4.1 Estimated Cost Upper Limit
We use an offline simulated auction system to estimate the cost upper limit of each channel. By removing budget constraints for all Ad requests, all matching campaigns will be recalled as the impression candidate, and the bidding, uGSP auction will be executed in order. The average cost of each channel in the past 30 days is counted as the estimated cost upper limit.

4.2 Estimate Cost Matrix
For large-scale model deployment, we make statistics of the 30 days CPC of a campaign on a channel as the cost C_{i,j}. In practice, we face two challenges:
- Conversion actions are inherently sparse: many campaign-channel pairs possessing no conversion action. We use a combination of estimated conversion rate and real conversion to count the number of conversions, so as to alleviate the sparsity.
- Partial cold start campaign: some Ad campaigns have no cost on some channels. We use the average cost per conversion of the Ad campaign itself as its cost matrix.

5 EXPERIMENT

5.1 Offline Setting
We experimentally evaluate AdCob in an offline setting using a simulated auction system and real-world datasets collected from our real online advertising system without any sampling.

5.1.1 Baselines: Apart from FCFS (first-come-first-served), two other relevant budget allocation methods: IDIL and unified budget allocation. All these prior methods focus on only one advertiser, so we directly use these budget allocation methods for 40%, 80% advertisers.

5.1.2 Dataset: We evaluate with an advertising data set from a real-world Internet e-commerce company, covering nearly two hundred thousand campaigns. The real dataset contains tens of millions of records with pCTR, pCVR (predicted by Deep Interest Network), real bid price (generated by OCPC bidding), click action, conversion action, and advertiser budget info. Each auction includes 5, 10, and 20 ad slots and 500 or 750 advertisers bidding.

5.1.3 Simulation system and metrics: We traverse each traffic record block by block (15-minute blocks) according to timestamp. For each record, we implement strict Generalised second-price auction. We report averaged CPC, total Conversions (Conv) and platform total Revenue (Rev). All metrics are normalized.

5.1.4 Offline results:
- CPC Reduction: coordinating all advertisers avoids excessive competition. Almost all advertisers achieve more conversions within prefixed budget.
- Revenue and Conversion Increase: overall revenue increased even though we did not optimize revenue directly, as budget utilization rate increased.
- Local Methods Cannot Work Well: when proportion of advertisers using local allocation increases, overall conversions and revenue decrease due to excessive competition.
- Impact of Entropy Coefficient epsilon: as epsilon increases, total conversions first increase then decrease.

Table 1 (offline, epsilon=5.50):
BASE: Rev=1.000, Conv=1.000, CPC=1.000
40% IDIL: Rev=0.981(-1.9%), Conv=0.947(-5.3%), CPC=1.018(+1.8%)
80% IDIL: Rev=0.973(-2.7%), Conv=0.901(-9.9%), CPC=1.056(+5.6%)
40% Unified: Rev=0.984(-1.6%), Conv=0.956(-4.4%), CPC=1.016(+1.6%)
80% Unified: Rev=0.965(-3.5%), Conv=0.910(-9.0%), CPC=1.052(+5.2%)
AdCob(Ours): Rev=1.029(+2.9%), Conv=1.191(+19.1%), CPC=0.864(-13.6%)

5.2 Online Setting
5.2.1 Online Budget Bucketing A/B Test: We introduce budget bucketing where traffic and budgets are both divided, ensuring experimental and control buckets do not compete for budget.

5.2.2 Online results (30 days):
Table 2:
BASE: Click=1.000, Conv=1.000, CPC=1.000
AdCob(Ours): Click=0.968(-3.2%), Conv=1.246(+24.6%), CPC=0.824(-17.6%)

6 DISCUSSION
This paper presents a cross-channel budget management framework coordinating all competing advertisers to allocate limited budget to different channels for overall conversion maximization. In the future, we plan to present a more comprehensive theoretical analysis of the Nash equilibrium efficiency with game theory. We also have interest in combining RL-based method to dynamically adjust the cost matrix. As for limitation, the method is more suitable for advertisers who use auto-bidding techniques like OCPX. For those who bid independently, they might adjust their behavior as a function of maximizing their own utility. We currently only apply our method on ad campaigns with automatic bidding.

REFERENCES
Key references include: Cuturi 2013 (Sinkhorn distances), Peyre et al. 2017 (Computational optimal transport), Nuara et al. 2019 (IDIL - dealing with interdependencies in multi-channel ad campaigns), Zhao et al. 2019 (unified framework for marketing budget allocation), Li et al. 2018 (efficient budget allocation for multi-channel advertising), Nuara et al. 2018 (combinatorial-bandit for bid/budget optimization), Wei et al. 2019 (optimal delivery with budget constraint), Edelman et al. 2007 (GSP auction), Galichon 2018 (OT methods in economics).
"""

PROMPT = f"""You are an academic paper analysis assistant. Extract a structured paper card from the following paper content. Return ONLY a JSON object (no markdown fences, no explanation) with these fields:

- title (string), authors (list of strings), venue (string), year (string)
- core_idea: 1-3 sentences summarizing the key insight
- motivation, problem_definition, method_summary: strings
- method_pipeline: list of ordered steps (strings)
- method_family: one of ["learning_based", "optimization_based", "probabilistic", "game_theoretic", "heuristic"]
- method_tags: list of strings
- contributions: list of strings
- key_references: list of objects with "title" and "relevance" fields
- assumptions: list of strings
- limitations: list of strings
- related_work_positioning: string
- algorithmic_view: string describing the algorithm in technical terms
- future_directions: string
- tasks: list of strings
- datasets: list of strings
- metrics: list of strings
- baselines: list of strings
- key_results: list of strings summarizing main quantitative findings
- ablation_focus: list of strings
- domain_tags: list of strings
- technical_tags: list of strings
- code_url: string or null
- reproducibility_score: one of ["high","medium","low","unknown"]
- reproduction_notes: string or null

Paper content:
{PAPER_TEXT}
"""

cfg = resolve_llm_config({"provider": "anthropic"})
print(f"Using provider: {cfg.provider}, model: {cfg.model}", flush=True)

import anthropic
import httpx

akwargs: dict = {"api_key": cfg.api_key or None}
if cfg.base_url:
    akwargs["base_url"] = cfg.base_url
    akwargs["http_client"] = httpx.Client(proxy=None, transport=httpx.HTTPTransport(proxy=None))

aclient = anthropic.Anthropic(**akwargs)
response = aclient.messages.create(
    model=cfg.model,
    max_tokens=8192,
    temperature=0.0,
    messages=[{"role": "user", "content": PROMPT}],
)
raw = "\n".join(block.text for block in response.content if hasattr(block, "text"))
print(f"Raw response length: {len(raw)}", flush=True)
json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
if json_match:
    card_data = json.loads(json_match.group(1))
else:
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        card_data = json.loads(json_match.group(0))
    else:
        card_data = json.loads(raw)

with open("/workspace/research-hub/paper_library/papers/card_2305.06883.json", "w") as f:
    json.dump(card_data, f, indent=2, ensure_ascii=False)
print(json.dumps(card_data, indent=2, ensure_ascii=False)[:3000])
