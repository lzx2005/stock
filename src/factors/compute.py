from factors.registry import FactorDefinition, FactorInputError

def apply_factor(defn: FactorDefinition, df, params: dict):
    missing = [c for c in defn.inputs if c not in df.columns]
    if missing:
        raise FactorInputError(f"{defn.name}: 缺输入列 {missing}（需要 {list(defn.inputs)}）")
    return defn.fn(df, **params)
