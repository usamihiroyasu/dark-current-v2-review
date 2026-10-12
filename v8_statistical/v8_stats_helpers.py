import hashlib,json,math,random,statistics

def sha(data):
    return hashlib.sha256(data).hexdigest()

def unique_object(pairs):
    if len(pairs) != len({k for k, _ in pairs}):
        raise ValueError("DUPLICATE_JSON_KEY")
    return dict(pairs)

def read_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))

def verdict(content):
    try:
        obj = read_json(content)
        if isinstance(obj, dict) and set(obj) == {"winner"} and obj["winner"] in ("A", "B", "tie"):
            return obj["winner"]
    except (ValueError, TypeError):
        pass
    return None

def binom_cdf(x, n, p):
    if not 0 <= p <= 1 or not 0 <= n or int(n) != n:
        raise ValueError("INVALID_BINOMIAL_ARGUMENT")
    if x < 0: return 0.0
    if x >= n: return 1.0
    if p == 0: return 1.0
    if p == 1: return 0.0
    return math.fsum(math.comb(n, k) * p**k * (1-p)**(n-k) for k in range(int(x)+1))

def cp_upper(x, n, alpha=0.05):
    if not 0 <= x <= n or n < 1 or not 0 < alpha < 1:
        raise ValueError("INVALID_CP_ARGUMENT")
    if x == n: return 1.0
    if x == 0: return 1-alpha**(1/n)
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo+hi)/2
        if binom_cdf(x, n, mid) > alpha: lo = mid
        else: hi = mid
    return (lo+hi)/2

def holm(pvalues):
    if any(not 0 <= p <= 1 for p in pvalues): raise ValueError("INVALID_PVALUE")
    adjusted = [None]*len(pvalues); previous = 0.0
    for rank, index in enumerate(sorted(range(len(pvalues)), key=lambda i: (pvalues[i], i))):
        previous = min(1.0, max(previous, (len(pvalues)-rank)*pvalues[index]))
        adjusted[index] = previous
    return adjusted

def quantile(values, probability):
    if not values or not 0 <= probability <= 1: raise ValueError("INVALID_QUANTILE")
    values = sorted(values); position = (len(values)-1)*probability
    left = math.floor(position); right = math.ceil(position)
    return values[left] + (position-left)*(values[right]-values[left])

def bootstrap(strata, seed, replicates):
    rng = random.Random(seed); results = []
    for _ in range(replicates):
        results.append(statistics.fmean(statistics.fmean(rng.choice(s) for _ in range(len(s))) for s in strata))
    return {"lower_one_sided_95": quantile(results, 0.05),
            "interval_two_sided_95": [quantile(results, 0.025), quantile(results, 0.975)],
            "replicates": replicates, "seed": str(seed), "quantile": "type7"}
