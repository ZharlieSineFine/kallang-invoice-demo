"""The registry builds all twelve checks with stable, unique rule_versions."""

from invoiceflow.contracts import Rule
from invoiceflow.rules import build_rules


def test_builds_twelve_rules_in_order(rules_config):
    rules = build_rules(rules_config)
    assert [r.id for r in rules] == [f"R{n:02d}" for n in range(1, 13)]


def test_every_rule_satisfies_the_protocol(rules_config):
    assert all(isinstance(rule, Rule) for rule in build_rules(rules_config))


def test_every_rule_has_a_unique_version(rules_config):
    rules = build_rules(rules_config)
    assert len({r.rule_version for r in rules}) == len(rules)


def test_version_changes_when_config_changes(rules_config):
    before = build_rules(rules_config)[0].rule_version
    changed = dict(rules_config)
    changed["tolerances"] = {**rules_config["tolerances"], "line_amount": "0.99"}
    assert build_rules(changed)[0].rule_version != before


def test_version_is_a_hash(rules_config):
    rules = build_rules(rules_config)
    assert all(len(r.rule_version) == 16 for r in rules)


def test_every_rule_ignores_missing_invoice(clean_ctx, rules_config):
    ctx = clean_ctx.model_copy(update={"invoice": None})
    for rule in build_rules(rules_config):
        assert rule.check(ctx) == (), rule.id
