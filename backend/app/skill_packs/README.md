# Mega skill packs (1000 skills)

20 domain packs × 50 skills each, loaded into `SKILL_CATALOG` via `load_mega_skills()`.

| Pack | Domain | Prefix |
|------|--------|--------|
| `01_sales` | Sales | `sales_` |
| `02_marketing` | Marketing | `mkt_` |
| `03_customer_success` | Customer success | `cs_` |
| `04_support` | Support | `sup_` |
| `05_finance` | Finance | `fin_` |
| `06_legal` | Legal & compliance | `leg_` |
| `07_hr` | HR & people | `hr_` |
| `08_operations` | Operations | `ops_` |
| `09_product` | Product | `prd_` |
| `10_engineering` | Engineering | `eng_` |
| `11_data` | Data & analytics | `dat_` |
| `12_content` | Content writing | `cnt_` |
| `13_social` | Social media | `soc_` |
| `14_project` | Project management | `pm_` |
| `15_procurement` | Procurement | `prc_` |
| `16_logistics` | Logistics | `log_` |
| `17_real_estate` | Real estate | `re_` |
| `18_healthcare` | Healthcare ops | `hc_` |
| `19_education` | Education & training | `edu_` |
| `20_executive` | Executive & strategy | `exec_` |

## Execution

Skills without a dedicated handler in `execute_skill` run through `_skill_catalog_deliverable` (LLM deliverable + brief).

## Regenerate

```bash
python scripts/generate_1000_skills.py
```

Then re-import / restart the API. Human-readable list: `SKILL_LIST_1000.md`.
