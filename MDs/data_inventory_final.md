# الجرد النهائي — Ports & Logistics RAG MVP

## 1. الداتا الحقيقية الموجودة فعلاً معانا

| # | الملف/المصدر | النوع | التفاصيل |
|---|---|---|---|
| 1 | `port_flows.shp/.dbf/.shx/.prj/.cpg` | Structured / Geospatial | 20,554 edge بين 836 ميناء (UN/LOCODE) في 169 دولة. أعمدة: `Port1`, `Port2`, `FLOWS`, `Country1`, `Country2`. WGS84 PolyLine. فيه 510 record بتخص مصر (EGALY, EGPSD, EGDAM, EGSOK). |
| 2 | `LPI.pdf` + `LPI_Methodology.pdf` | Unstructured (نصي + جداول) | World Bank "Connecting to Compete 2025" (LPI 2.0) الكامل + دليل المنهجية. فيه مثال حقيقي جاهز لمصر (Figures 7 & 8 — مقارنة connectivity/dwell time بالأقاليم). |
| 3 | `HbR_Annual_report_2025_highlights.pdf` | Unstructured (نصي + جداول مالية) | التقرير السنوي الكامل لـ Port of Rotterdam Authority 2025 — 85 صفحة إنجليزي. فيه narrative عن الاستراتيجية والـ ESG والمخاطر، وجداول مالية حقيقية (balance sheet, income statement). |
| 4 | `MSC-MEPC_3-Circ_4-Rev_1.pdf` | Unstructured (schema/reference) | دائرة IMO الرسمية اللي بتعرّف الحقول القياسية لتقارير حوادث السفن (GISIS MCI module, Appendices 1-5). مستخدمة كـ **schema حقيقي** لجدول `incident_reports`. |
| 5 | `Critical_Port_Infrastructure_Risks_PWSA_BOIR_Redacted.pdf` | Unstructured (تحقيق فيدرالي) | تقرير Board of Inquiry من خفر السواحل الأمريكي، 55 صفحة — عن حادثة DALI/جسر Francis Scott Key وتقييم مخاطر شامل لـ 10 موانئ أمريكية. الملحقات الحساسة (Appendices C-M) اتشالت (Redacted). |
| 6 | `ais_real_sample_template.csv` | Semi-structured | 9 صفوف حقيقية من ملف Danish Maritime Authority (`aisdk-2023-02-15.csv`) — نفس اللحظة الزمنية، بتفيد كـ **format template** بس مش حركة زمنية. |
| 7 | [tayljordan/ais على GitHub](https://github.com/tayljordan/ais) | Semi-structured | 10,000 سفينة حقيقية من AISHub، 4.79 ميجا. **لينك متاح، لسه محتاج تنزّله وترفعه**. |
| 8 | [SCA Tolls Table](https://www.suezcanal.gov.eg/English/Navigation/Tolls/Pages/TollsTable.aspx) + [PDF الجداول](https://www.suezcanal.gov.eg/English/Navigation/NavigationCirculars/Documents/Cir_14-2022_tables_EN.pdf) | Reference / أرقام | جدول رسوم عبور قناة السويس الرسمي حسب نوع السفينة. |
| 9 | إحداثيات NOAA AccessAIS (Port of LA/Long Beach) | اختياري | جاهزة لو حبيت تجيب عينة AIS فيها حركة زمنية حقيقية لاحقاً — مش لازمة دلوقتي. |

---

## 2. الداتا اللي هتتعمل Synthetic — ومين مربوط بمين

| الجدول | طريقة التوليد | مربوط بمصدر حقيقي؟ |
|---|---|---|
| `ports` | **مش synthetic** — مستخرج مباشرة | ✅ من `port_flows.shp` (836 ميناء حقيقي) |
| `documents` (تقارير/سياسات كاملة) | **مش synthetic** — يتحط زي ما هو | ✅ HbR + LPI + IMO + USCG (4 مستندات حقيقية) |
| `roles`, `employees`, `departments` | Synthetic كامل (Faker) | ❌ لا — حجم افتراضي: 5 أقسام، ~100 موظف، 3 أدوار (employee/manager/ceo) |
| `vessels`, `containers` | Synthetic كامل | ❌ لا — أرقام وحالات منطقية بس |
| `invoices` | Synthetic **مربوط بأرقام حقيقية** | ✅ رسوم مبنية على جدول SCA الرسمي |
| `ais_tracking` (semi-structured) | Synthetic **مربوط بـ template** | ✅ بنية وقيم واقعية من عينتي Danish + AISHub |
| `incident_reports` (نص حر داخل RAG) | Synthetic **بـ few-shot grounding** | ✅ مبني على أسلوب وهيكل تقرير USCG + schema الـ IMO |
| `edi_messages` | Synthetic كامل | ⚠️ **لسه من غير عينة حقيقية** — فجوة مفتوحة |
| عقود / Bill of Lading | Synthetic كامل | ⚠️ **لسه من غير template حقيقي** — فجوة مفتوحة |
| `audit_log` | Synthetic كامل | ❌ لا يوجد مصدر خارجي، بيتولد من محاكاة أحداث الاستخدام |
| مستندات عربي/إنجليزي مختلطة | Synthetic كامل | ⚠️ محدودية معروفة — مفيش حل مصدري متاح |

---

## 3. تحديات معمارية (مش نواقص بيانات — محتاجة تصميم وقت بناء الـ generator)

1. **الاتساق السببي بين الجداول**: لازم "event timeline" مركزي لكل شحنة/سفينة، وكل جدول (Postgres/Mongo/Qdrant) ياخد قيمه من نفس الـ timeline عشان ميحصلش تناقض بين الحالة في جدول وحركة AIS وملاحظة incident report.
2. **حالات RBAC الاستثنائية**: لازم تتحقن بشكل متعمد في generator الموظفين (صلاحيات مؤقتة، تعارض مهام) — مش هتطلع تلقائي من generator عادي.

---

## 4. الأخبار والمستجدات — مش جزء من التوليد أصلاً

الـ agent هيستخدم **web_search كـ tool call لايف** وقت السؤال عن مستجدات (زي "إيه اللي حصل في قناة السويس الأسبوع ده")، مش جزء من ingestion pipeline أو RAG corpus الثابت. القرار (بحث حي ولا معرفة داخلية) هيتصمم كـ tool routing logic في طبقة الـ agents لاحقاً.

---

## الخلاصة

- **7 مصادر حقيقية** جاهزة فعلاً (منهم 2 لسه محتاجين خطوة تنزيل بسيطة منك: عينة AISHub الكبيرة، وعينة NOAA لو حبيت).
- **جدولين بس** (`ports`, `documents`) هيتبنوا من الداتا الحقيقية مباشرة من غير توليد.
- **باقي الجداول** هتتولد synthetic، أغلبها مربوط بمصدر حقيقي كـ anchor (مش توليد من الفراغ).
- **فجوتين مفتوحتين** (EDI sample, Bill of Lading template) مش حرجين — نقدر نسدهم لاحقاً لو احتجنا.
- **الأخبار** خارج نطاق الداتا بالكامل — tool call حي مش corpus.
