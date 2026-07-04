# OJK Tree Mapping Audit

Date: 2026-05-25  
Scope: `data/trees/OJK_POJK.yaml` first-pass legal citation review.

## Sources Checked

- OJK official PDF: `POJK No. 6/POJK.07/2022` on consumer and public protection in the financial services sector.
- Official source URL: https://www.ojk.go.id/id/regulasi/Documents/Pages/Perlindungan-Konsumen-dan-Masyarakat-di-Sektor-Jasa-Keuangan/POJK%206%20-%2007%20-%202022.pdf

## Main Finding

The current OJK YAML repeatedly cites `POJK No. 6/POJK.07/2022 Pasal 28` and `Pasal 29` for advertising and disclosure issues. This is likely not legally precise.

In the official POJK 6/2022 text:

- `Pasal 16` requires product/service information to be clear, accurate, true, easy to access, and not potentially misleading.
- `Pasal 17` requires the product/service summary to include benefits, risks, requirements/procedures, costs, and relevant additional information.
- `Pasal 18` requires the information referred to in Pasal 16(1) to be delivered during marketing and before contract signing.
- `Pasal 19` governs delivery of product/service summary information before consumer decisions or contract signing.
- `Pasal 21` governs mandatory identification in offers, promotions, and advertisements: PUJK name/logo and licensed/supervised-by-OJK statement.
- `Pasal 22` prohibits offering products/services that harm or potentially harm consumers by abusing the condition of consumers who have no other choice.
- `Pasal 28` concerns misuse of consumer circumstances in preparing product/service agreements.
- `Pasal 29` concerns confirmation of consumer understanding of contract clauses before signing.

## Recommended Citation Mapping

| Current Rule | Current Citation | Recommended Primary Citation | Reason |
|---|---:|---:|---|
| `ojk_1_keuntungan_pasti` | Pasal 29 | Pasal 16(1), Pasal 18(1) | Guaranteed/definitive returns are best framed as unclear, inaccurate, untrue, or potentially misleading information during marketing. |
| `ojk_2_bebas_risiko` | Pasal 29 | Pasal 16(1), Pasal 17(1) | “Risk-free” or principal-safety claims relate to misleading information and risk disclosure. |
| `ojk_3_risiko_tidak_diungkap` | Pasal 29 | Pasal 17(1), Pasal 18(1), Pasal 19 | Missing risk disclosure belongs to product summary and information delivery obligations. |
| `ojk_4_biaya_tidak_diungkap` | Pasal 28 | Pasal 17(1), Pasal 18(1), Pasal 19 | Missing fees/costs belongs to product summary and pre-contract information delivery. |
| `ojk_5_perbandingan_tanpa_dasar` | Pasal 29 | Pasal 16(1) | Unsupported comparative superiority is a misleading/inaccurate information issue. |
| OJK license/logo disclosure | not separated | Pasal 21 | If we add an OJK-specific rule for ads/promotions, this should be a separate mandatory-disclosure rule. |

## Recommended Next Edit

Do not delete the current OJK tree. Instead, update `law`, `citation`, prompt text, and comments to cite `Pasal 16-19` and `Pasal 21` as appropriate, while leaving the detection patterns intact for now.

This keeps the functional MVP stable while improving legal defensibility for presentation.
