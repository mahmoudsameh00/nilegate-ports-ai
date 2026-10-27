<div dir="rtl">

# شرح Stage 1 — الـ Weekly Finance Pack (من Phase 0 لحد قفل §5f، 2026-10-10 → 2026-10-23)

الملف ده شرح كامل بالعامية لكل اللي اتعمل في Stage 1 من خطة الـ agents: كل Phase كان هدفها إيه، اتبنت إزاي، كان
قدامنا أنهي اختيارات واخترنا إيه وليه، قابلنا مشاكل إيه واتحلت إزاي، والملفات اللي اتعملت وكل واحد بيعمل إيه.
مصادر الشرح ده (لو عايز التفاصيل الخام): `docs/plans/Agents_plan.md` (الخطة + قسم Progress بكل يوم)، و
`docs/decisions.md` من ADR-045 لحد ADR-054، و`ARCHITECTURE.md`، وملفات الـ checkpoints في `pipelines/checkpoints/agents/`.

---

## 1. الفكرة في كلمتين

**المشكلة اللي بنحلها:** فريق الـ Finance في أي شركة شحن بيضيّع ساعات كل أسبوع يعمل تقرير: كام فوترنا، كام اتحصّل، مين
متأخر في الدفع، إيه الفواتير اللي فيها غلط، وليه الأرقام اتغيرت عن الأسبوع اللي فات. ده شغل متكرر، والأرقام فيه لازم تبقى
صح 100%.

**اللي بنيناه:** نظام بيعمل التقرير ده لوحده كل أسبوع لشركة وهمية اسمها NileGate (بتاخد رسوم عبور قناة السويس):

1. **Dashboard في Power BI** (5 صفحات) بيقرا الأرقام مباشرة من PostgreSQL.
2. **تقرير PowerPoint من 10 slides** بالإنجليزي، بيكتبه فريق من الـ agents (LLMs مجانية)، وكل رقم فيه جاي من tool
   ومتراجع بكود قبل ما حد يشوفه.
3. **موافقة بشرية:** التقرير ميتنشرش غير لما Finance manager يوافق عليه (أو يعدّله أو يرفضه).
4. **بيشتغل لوحده كل يوم اتنين** الساعة 10:30 من Windows Task Scheduler.
5. **Q&A:** تقدر تسأل سؤال مالي بالإنجليزي أو بالعامية المصري ("كام فوترنا في أسبوع 23؟") ويرد بأرقام من نفس الـ tools
   وبنفس الصلاحيات.

**أهم قاعدة في المشروع كله:** الـ LLM **مبيكتبش رقم بنفسه أبداً**. الأرقام بتيجي من SQL views، والـ LLM بيكتب "إشارة"
للرقم (اسمها slot)، والكود هو اللي بيحط الرقم، وبعدين Validator (كود مش LLM) بيتأكد من كل رقم قبل ما يتعرض على الإنسان.

**الرحلة الكاملة لتقرير أسبوع واحد:**

```text
Task Scheduler (الاتنين 10:30)
 → Weekly_pack.py scheduled   ← بيختار الأسبوع الجاي في الـ replay (2025)
   → الـ graph بتاع LangGraph "weekly_pack" (كل خطوة بتتحفظ في PostgreSQL):
      1 readiness   (كود)  : الأسبوع ده بياناته كاملة؟ لو لأ → وقف وقول ليه
      2 kpi         (كود)  : يجيب أرقام الأسبوع من الـ finance views (5 datasets)
      3 audit       (كود)  : يراجع كل فاتورة على جدول الرسوم ويطلّع الأخطاء
      4 insight     (LLM)  : يحلل ليه الأرقام اتغيرت، ويستخدم tools (أخبار، حركة السويس، مستندات)
      5 writer      (LLM)  : يكتب الـ deck كـ slots مش أرقام
      6 validator   (كود)  : V1–V8؛ لو فيه غلط → يرجع للـ writer بالمشاكل (مرتين بالكتير)
      7 approval    (إنسان): ⏸ الـ graph بيقف ويستنى Finance manager: approve / edit / reject
      8 publisher   (كود)  : يحفظ deck.pptx + 3 ملفات JSON في reports/2025-Www/
```

---

## 2. قاموس الكلمات اللي هتتكرر

| الكلمة | معناها هنا |
|---|---|
| **Stage / Phase** | الخطة مرحلتين كبار (Stage 1 = Finance، Stage 2 = Operations). كل Stage متقسم Phases مرقمة. |
| **ADR** | Architecture Decision Record: قرار مكتوب في `docs/decisions.md` بالسياق والاختيارات والسبب. مبيتمسحش، بيتعدّل بـ amendment. |
| **D1…D14** | القرارات الكبيرة اللي إنت جاوبت عليها يوم 2026-10-09 قبل ما نبدأ (الخطة §7). |
| **P4-1، P5-3…** | قرارات التصميم التفصيلية لكل Phase (اتسألت قبل التنفيذ). |
| **D-P5-6، D-P7-14…** | Deviations: حاجة اتعملت مختلف عن التصميم أثناء التنفيذ، أو اكتشاف غيّر حاجة. كلها متسجلة في Progress. |
| **tool** | function بايثون الـ agent يقدر ينادي عليها (زي `finance_kpi`). بترجع `ToolResult` فيه status وrows ومصدر. |
| **evidence** | نتايج الـ tools اللي اتجابت للأسبوع، محفوظة في الـ state بـ id (زي `kpi.weekly`، `audit.week`). |
| **slot** | بدل ما الـ LLM يكتب "8.39 M SDR"، يكتب `{kpi.weekly:billed_sdr\|M}`، والكود يحط الرقم. |
| **Validator** | كود بيراجع الـ deck: كل رقم مربوط بحقل حقيقي، الإشارات (up/down) صح، الـ drivers صح، والملف نفسه سليم. |
| **RunContext** | مين اللي شغّال (الموظف) وأنهي داتا (live ولا test). بيتبعت للـ tools من الكود، **الموديل عمره ما بيشوفه**. |
| **RBAC** | الصلاحيات (ADR-006): كل مورد له level (1–3) وقسم؛ الموظف بيشوف لحد الـ ceiling بتاعه أو قسمه. |
| **checkpoint** | LangGraph بيحفظ حالة الـ graph بعد كل خطوة في PostgreSQL، فلو الجهاز وقع يكمّل من نفس النقطة. |
| **interrupt** | الـ graph بيقف عند خطوة الموافقة ويستنى قرار إنسان (ساعات أو أيام). |
| **skill** | ملف `SKILL.md` فيه تعليمات للـ agent (زي إزاي يكتب الأرقام)، بيتحمّل في الـ prompt وقت ما يتحتاج بس. |
| **fallback** | موديل احتياطي من provider تاني لو الأساسي وقع أو خلص الـ quota. |
| **quota** | الحد المجاني: flash-lite = 500 request في اليوم، OpenRouter = 50، Groq = 1,000 لكل موديل. |
| **fake models** | `FakeRoles`: بديل للـ LLM بيرد ردود محسوبة من الأرقام، علشان نجرّب الـ graph كله على 52 أسبوع من غير ما نصرف quota. |
| **golden weeks / golden set** | أسابيع وأسئلة اتختارت واتقفلت بـ hash **قبل** أي تجربة، علشان التقييم يبقى عادل. |
| **planted errors** | أخطاء إحنا زارعينها عمداً في نسخة test من الفواتير (`finance_test`) علشان نشوف الـ agents هيمسكوها ولا لأ. |
| **D7** | شروط القبول الصارمة لـ Stage 1: أرقام الـ deck 100%، الأخطاء المزروعة ≥ 95%، false alarms ≤ 5%، كل claim صح، كل رقم ليه مصدر، تسريب صلاحيات = 0. |
| **ADR-052** | قاعدة "إمتى نقبل تغيير": تجربتين للقديم وتجربتين للجديد، ولا gate يرجع لورا، ولا score رئيسي يقع أكتر من 0.03. |
| **baseline / candidate (c1, c2…)** | الـ baseline = آخر نتيجة مقبولة. الـ candidate = تعديل بنجربه ونقارنه بيها. |
| **SDR** | Special Drawing Rights: العملة اللي كل الفلوس متخزنة بيها في المشروع (ADR-003). |

---

## 3. الـ Phases واحدة واحدة

### Phase 0 — الأساس واختيار الموديلات (2026-10-10 → 10-12) · ADR-045

**الهدف:** نجهّز المكتبات، ونتأكد إن الـ API keys المجانية شغالة، ونختار أحسن LLM مجاني لكل "دور" بتجربة عادلة
(bake-off) مش بالانطباع.

**القرارات اللي اتاخدت قبل ما نبدأ (D1–D14، يوم 2026-10-09):**
- **D1:** LLMs من free APIs بس (Google AI Studio، Groq، OpenRouter)، وموديلين لكل دور (أساسي + احتياطي).
- **D2:** الـ pack = workflow ثابت (StateGraph)، مش supervisor حر. **ليه؟** شكل التقرير ثابت، والأرقام لازم تطلع نفسها كل
  مرة، وكل خطوة لازم تتختبر لوحدها.
- **D3:** الـ checkpoints في PostgreSQL. **D5:** Power BI Desktop مجاني + DirectQuery. **D7:** شروط التقييم الصارمة.
  **D8:** LangSmith للمتابعة. **D9:** التقرير بيتحفظ بس، مفيش email. **D12:** "الساعة" = replay لأسابيع 2025 الـ 52.
- **D13 (2026-10-10):** تعليمات الـ agents تبقى Agent Skills (`SKILL.md`) إحنا اللي بنكتبها، مش skills جاهزة من الإنترنت.
  **ليه؟** معرفة الشركة مش موجودة في أي مكان تاني، و2026 audits لقت ~13% من skills الـ registries فيها مشاكل خطيرة.
- **D14:** skills رسمية من LangChain للـ coding assistant بس (مش للـ agents)، بعد مراجعة كل ملف.

**اتبنت إزاي:**
1. branch اسمه `feat/agents`، و12 package اتضافوا بـ `uv add` بأرقام ثابتة `==` (langchain، langgraph، langchain-google-genai،
   langchain-groq، langchain-openai لـ OpenRouter، langgraph-checkpoint-postgres، psycopg-pool، pydantic، python-pptx،
   matplotlib، langsmith).
2. `pipelines/agents/llm.py`: البوابة الوحيدة لأي LLM في المشروع. فيه: سجل الـ providers وحدودهم، cache لكل رد (نفس
   السؤال = نفس الرد من غير call جديد)، Budget للدقيقة، وعدّاد يومي للـ quota محفوظ على الديسك.
3. `LLM_smoke_test.py`: جرّب كل key بـ call واحدة فيها tool calling. الـ 9 موديلات المرشحة اشتغلوا.
4. `LLM_bakeoff.py`: الامتحان نفسه. 4 مهام اتقفلت في `bakeoff_tasks.json` **قبل أي call**:
   - **T1** tool calling (20 سؤال: الـ tool الصح بالـ arguments الصح).
   - **T2** ملخص أسبوعي من جدول أرقام: **أي رقم مش موجود في الجدول = الموديل يطلع برا دور الـ Writer** (hard gate).
   - **T3** structured output (قايمة أخطاء فواتير كـ Pydantic object).
   - **T4** أجوبة RAG على الـ 40 سؤال الذهبي (fact recall + citations).

**المشاكل وحلها:**
- **حساب الرسوم مش متطابق في نص القرش:** الفواتير المتخزنة مش ماشية على قاعدة تقريب واحدة (half-up يسيب 34 فرق قرش). الحل:
  المقارنة بفرق أقل من نص قرش.
- **نقل المشروع لـ `D:\Project` حوّل الملفات لـ CRLF** فالـ hashes بتاعة الملفات المقفولة اتكسرت رغم إن المحتوى نفسه. الحل:
  `.gitattributes` بيجبر `*.json / *.jsonl / *.csv` على LF.
- **حدود مجانية مخفية:** `gemini-3.8-flash` = 20 request في اليوم بس (ميقدرش يعمل تقرير واحد)، و`inkling` رافض أي API call
  (403)، و`gemma-4-31b-it` بطيء جداً (متوسط 35 ثانية) وبيقع بـ 500. الحل: الموديلات دي اتجربت على subset صغير (LITE) بس.
- **أخطاء server متكررة:** لو نفس الـ request وقع بـ 5xx في تشغيلتين منفصلتين، بيتسجل كفشل (`server_error_repeated`) بدل ما
  نفضل نستنى للأبد.
- **اكتشاف مهم:** أكبر موديل (`gpt-oss-120b`) كتب "849.9 k" بدل "−850.0 k" (قطع الرقم وشال الإشارة) → اتشال من دور الـ
  Writer. **الدرس:** حجم الموديل مش ضمان للأرقام، علشان كده الـ Validator هيبقى hard gate.

**النتيجة (ADR-045):**
- Writer / Insight: `qwen/qwen3.8-27b` (Groq) أساسي + `gemini-3.5-flash-lite` احتياطي.
- Tools: `gemini-3.5-flash-lite` أساسي (الوحيد اللي جاب T1 كله صح) + `openai/gpt-oss-20b` (Groq) احتياطي.
- (اتغيّر بعدين في Phase 5، وهتشوف ليه.)

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `pipelines/agents/llm.py` | كل call لأي LLM بتعدي من هنا: الـ cache، الـ quota، الـ per-minute budget، تصنيف الأخطاء (quota / too_large / model_missing / server_error_repeated). |
| `pipelines/scripts/agents/LLM_smoke_test.py` | يتأكد إن كل key شغال وإن الموديل بيعرف tool calling. |
| `pipelines/scripts/agents/LLM_bakeoff.py` | الامتحان بين الـ 9 موديلات بقواعد مقفولة. |
| `Data/processed/agents/eval/bakeoff_tasks.json` | المهام المقفولة بـ hash. |
| `Data/processed/agents/eval/llm_bakeoff_2026-10-12.json` | النتايج. |
| `pipelines/lib/common.py` (`SECRET_KEYS`) + `.env.example` | أسماء الـ keys اللي بتتخفى من أي log. |
| `.gitattributes` | يمنع مشكلة CRLF. |

---

### Phase 1 — داتا مالية وهمية (2026-10-13 → 10-14) · ADR-046 · migration 012

**الهدف:** الداتا الموجودة كان فيها 1,000 فاتورة بس، **من غير عملاء ولا مواعيد دفع ولا مدفوعات ولا budget**. يعني
مستحيل نحسب DSO أو AR aging أو أكبر عملاء أو انحراف عن الـ budget. محتاجين نولّد الحاجات دي بشكل واقعي.

**أكبر اكتشاف في الـ Phase:** عمود `invoices.status` (Paid / Issued / Pending) طلع **عشوائي** على مدار السنة: 689 من
1,000 فاتورة "مش مدفوعة". لو عملنا مدفوعات تمشي معاه، الشركة هتبان في أزمة تحصيل (DSO ≈ 250 يوم).

**القرار (عدّل D6):** المدفوعات تمشي على شروط وسلوك كل عميل، و`status` **يفضل زي ما هو** (ADR-013: مبنعيدش توليد جداول
خلصت) بس بيتوثّق بـ COMMENT إنه "label قديم مش حالة الدفع". كل الـ views بتحسب الحالة من التواريخ.

**القواعد اللي إنت وافقت عليها (R1–R10، الخطة §4a):**
- **R1:** 40 عميل وهمي في 6 segments (حاويات 8، tankers 10، bulk 10، Ro-Ro 5، cruise 3، agents 4)، **من غير أسماء شركات
  حقيقية**.
- **R2:** كل مركب من الـ 500 ليه عميل، بتوزيع Zipf علشان الإيرادات تتركز (أكبر 10 عملاء ≈ 57%).
- **R3:** شروط الدفع 30 / 45 / 60 يوم وتقييم A / B / C متخزنين. **سلوك الدفع** (ملتزم / عادي / بطيء / متأخر دايماً /
  بيعترض) **مش متخزن** في الجدول، في الـ manifest بس. **ليه؟** لو اتخزن، الـ agent كان هيقرا الإجابة بدل ما يستنتجها.
- **R4:** مدفوعات كاملة (مفيش دفع جزئي)، والتأخير حسب السلوك، ومفيش مدفوعات بعد 2026-03-31.
- **R6:** budget أسبوعي من **نموذج تخطيط مستقل عن الفواتير** (عدد المراكب × 2 عبور في السنة × رسوم المركب المتوسط، ±6%
  موسمي). متظبطش بعد ما شفنا الأرقام الفعلية.
- **R7:** نسخة تقييم منفصلة في schema `finance_test`: 4 أسابيع فيها **5 أخطاء مزروعة** (سعر band غلط، أرقام SCNT
  متبدلة، laden / ballast متبدلين، SFU متسعّر ballast، فاتورة مكررة) + budget miss.
  **Deviation:** النسخة دي **ملهاش عمود `test_case`**، لنفس السبب بتاع R3. الإجابات في `finance_test_answer_key.json` بس.

**اتبنت إزاي:** `Finance_generator.py` اشتغل **dry run** الأول وطبع التوزيعات من غير ما يكتب حاجة، وإنت راجعتها. بعدها
كتب 6 ملفات CSV + manifest + migration `012_finance_data.sql`. إنت طبّقت الـ migration، واتعمل audit
(`verify_readonly.sql` §17). التشغيل التاني بـ seed مختلف للـ hash غيّر **0 ملفات**.

**النتيجة:** أكبر 10 عملاء = 57% من الفواتير، DSO = 55 يوم، 0.6% مش مدفوع عند آخر الداتا، الـ budget 302.1 M مقابل فعلي
267.9 M (أقل بـ 11.3%).

**مشكلة صغيرة:** Docker اتقفل بشكل مش نضيف فالـ statistics اتمسحت (`tables_never_analyzed = 13`)، والحل `ANALYZE`.

**وبعدها:** يوم 2026-10-14 إنت قررت تشيل الـ "data guard" (ADR-037 amendment 2): الداتا كلها وهمية أو public، فنتعامل
مع الـ free tier كأنه مدفوع من غير قيود.

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `pipelines/scripts/synthetic/Finance_generator.py` | يولّد العملاء والمدفوعات والـ budget ونسخة الـ test بـ seed ثابت. |
| `Data/processed/synthetic/finance/*.csv` + `manifest.json` | الملفات المتولدة (customers، vessel_customer، payments، budget_weekly، finance_test_invoices، finance_test_budget). |
| `Data/processed/agents/eval/finance_test_answer_key.json` | الإجابات الصح للأخطاء المزروعة. |
| `db/migrations/012_finance_data.sql` | يحمّل الداتا في PostgreSQL بقيود (CHECKs، FKs، COMMENTs). |
| `db/verify_readonly.sql` §17 | يتأكد من الـ invariants (كل مركب له عميل، كل دفعة = مبلغ الفاتورة…). |
| `pipelines/checkpoints/synthetic/Finance_generator.md` | قصة السكربت خطوة خطوة. |

---

### Phase 2 — الـ schema المالي: views بس (2026-10-14) · ADR-047 · migrations 013–014

**الهدف:** نفس الرقم لازم يطلع في Power BI وفي الـ PowerPoint، لأن الـ Validator هيقارن بالحرف. يعني كل KPI يتحسب **في
مكان واحد بس**.

**القرارات (P2-1…P2-9):**
1. **DSO** = الـ AR آخر الأسبوع ÷ الفواتير في آخر 91 يوم × 91.
2. **أول 13 أسبوع** ملهمش 91 يوم تاريخ (الداتا بتبدأ 2025-01-01)، فبيستخدموا المتاح والصف عليه `is_warmup = true`.
3. **ISO weeks صارمة**، و"as of" = الأحد 23:59. آخر 4 فواتير في ديسمبر بتقع في 2026-W01، برا الـ 52 أسبوع.
4. **Views بس، من غير SQL functions** (صف لكل `report_week`). Power BI بيقرا الـ view، والـ tool بيعمل
   `WHERE report_week = %s`.
5. **الصلاحيات:** `finance.*` = level 2 / Finance، واتثبتت بـ matrix على كل الـ 100 موظف.
6. **Role اسمه `finance_bi`** (قراءة بس، على `finance` بس) لـ Power BI.
7. **أسابيع المراجعة اليدوية:** 5 (warm-up)، 16 (أهدى أسبوع)، 23 (الذروة)، 49 (أسبوع test نضيف).
8. **التقريب مرة واحدة في الآخر:** فلوس رقمين عشري، نسب رقمين، أيام رقم واحد.

**اتبنت إزاي:**
- كل metric اتحسب الأول بـ pandas من الـ CSVs (من غير داتابيز) وإنت شفته على أسبوع 27.
- بعدين `013_finance_views.sql` اتكتب بالإيد: 12 view.
  - **dims:** `dim_date`، `dim_week`، `dim_customer`، `dim_vessel`، `dim_toll_band`.
  - **facts:** `fact_invoice` (فيه الـ due date المحسوب)، `fact_payment`، `fact_ar_snapshot`.
  - **KPIs:** `kpi_weekly`، `kpi_weekly_category`، `kpi_customer_13w`، `kpi_overdue_list`.
- `Finance_views_check.py` قارن الـ 4 KPI views بمرجع pandas مستقل على **الـ 52 أسبوع**: الفرق 0.000.
- في Phase 3 اتضاف view رقم 13 (`kpi_weekly_trend`، migration 014): كل أسبوع معاه 13 صف trend، فالـ slicer يحرك الـ chart من
  غير DAX.

**اكتشافات:**
- مفيش فواتير 2024، فالـ AR بيبدأ من صفر ويطلع لحد أسبوع 12 تقريباً.
- معادلتين الـ DSO بيختلفوا لحد ±9 أيام، فاخترنا واحدة ووثّقنا التانية كبديل مؤجل.
- `dim_vessel` شايل أسماء المواني جواه، لأن `finance_bi` مينفعش يعمل join على `public.ports`.

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `db/migrations/013_finance_views.sql` | الـ 12 view + الـ role `finance_bi` + COMMENT على كل عمود. |
| `db/migrations/014_finance_trend_view.sql` | view الـ trend (598 صف). |
| `docs/finance_metrics.md` | تعريف واحد لكل KPI (المرجع الوحيد). |
| `pipelines/scripts/finance/Finance_views_check.py` | يقارن الـ views بمرجع pandas مستقل + أسابيع المراجعة اليدوية + matrix الصلاحيات. |
| `db/verify_readonly.sql` §18 | الـ audit بتاع الـ views. |

---

### Phase 3 — الـ Dashboard في Power BI (2026-10-14 → 10-15) · ADR-048

**الهدف:** dashboard من 5 صفحات، أرقامه = الـ KPI views بالظبط، من غير حساب مدفوع ولا gateway ولا نسخة من الداتا،
والموديل نفسه يبقى في git.

**القرارات:**
- **Power BI Desktop + PBIP:** الصيغة النصية (TMDL للموديل و PBIR للصفحات)، فتتراجع في git. الـ `.pbix` و`cache.abf` و
  `localSettings.json` في `.gitignore`.
- **DirectQuery** بـ login اسمه `ports_bi` (عضو في `finance_bi` بس، قراءة بس): الأرقام بتبقى current وقت ما تفتح، من غير
  refresh.
- **الموديل اتبنى بـ Power BI Modeling MCP الرسمي** (`@microsoft/powerbi-modeling-mcp@1.0.0` في `.mcp.json`)، يعني
  الـ assistant بيعدّل الموديل بأوامر. Node.js 24 اتنزل بـ winget.
- **P3-5…P3-8:** أسماء جداول مفهومة (Weekly KPIs، Invoices، Week…)، كل الـ measures في `Weekly KPIs` في folders، كل عمود
  `summarizeBy = None`.
- **DAX رفيع، 3 أنماط بس:** `SELECTEDVALUE` لأرقام الأسبوع، و`HASONEVALUE(Week)` للجداول اللي مينفعش تتجمع، و`SUM` للـ
  facts. **مفيش أي KPI logic في DAX** (وإلا يبقى فيه تعريفين لنفس الرقم).
- **18 relationship** many-to-one، اتجاه واحد، **Assume referential integrity = off**. **ليه off؟** لو on، Power BI يعمل
  INNER JOIN ويرمي الـ 4 فواتير بتوع 2026-W01 والـ 152 دفعة اللي في 2026.
- **slicer أسبوع واحد** متزامن على كل الصفحات.
- **إنت اخترت:** الـ assistant يبني الصفحات على الشاشة بـ computer use وإنت بتتفرج، ويشرح كل visual. الدليل المكتوب كان
  تقيل.

**المشاكل وحلها:**
- **`The key didn't match any rows`:** Desktop كان مفتوح قبل migration 014 وعامل cache لقايمة الجداول. الحل: save + reopen.
- **Ctrl+S مكانش بيحفظ تعديلات الـ MCP** طول ما فيه banner "relationships modified". الحل: *Refresh now* الأول، وبعدها
  File → Save.
- **الـ Card الجديد بيتجاهل `,,`** في الـ format. الحل: `#,0.00`، والـ card بيختصر لوحده ("8.39M").
- **مجموع نسب العملاء المقرّبة** (59.44%) ≠ الـ KPI (59.46%). الحل: الـ total row مقفول، والـ card بيعرض الـ KPI.
- **Docker وقف بعد restart** فـ Power BI فتح من غير موديل. الحل: الـ containers بقت `--restart unless-stopped` (P3-12).
- **`open_application` فتح نسخة تانية فاضية** من Power BI. الدرس: نستخدم النافذة اللي مفتوحة.

**الصفحات:** Overview (6 كروت + Billed vs Budget)، Revenue (حسب فئة المركب، laden / ballast، band، أكبر 10 طرق، trend 13
أسبوع)، Receivables (aging buckets، DSO trend، قايمة المتأخرين)، Customers (أكبر 10، تركيز الإيرادات)، Exceptions (كانت
placeholder لحد §5f F6).

**التأكيد:** كل رقم في صفحات 1–4 اتقارن بـ DAX بـ `finance.kpi_weekly` لأسابيع 5 / 23 / 49، ومتطابق.

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `powerbi/NileGate_Finance.pbip` | المشروع (افتحه وPostgreSQL شغال). |
| `powerbi/NileGate_Finance.SemanticModel/definition/` | الموديل TMDL: `model.tmdl`، `relationships.tmdl`، `tables/*.tmdl` (13 جدول دلوقتي). |
| `powerbi/NileGate_Finance.Report/definition/pages/` | الصفحات الـ 5 والـ visuals (PBIR JSON). |
| `db/create_finance_bi_user.ps1` | يعمل الـ login `ports_bi` ويكتب الباسورد في `.env`. |
| `db/check_finance_bi_user.py` | 11 اختبار: يقرا `finance`، مرفوض من `public` و`finance_test` ومن أي كتابة. |
| `.mcp.json` | تسجيل الـ Power BI Modeling MCP. |

---

### Phase 4 — الـ Tools والـ Skills (2026-10-18 → 10-19) · ADR-049 · migration 015

**الهدف:** الأدوات اللي الـ agents هتستخدمها، كل واحدة متختبرة لوحدها، والصلاحيات مستحيل تتسرب، وفيه skills مكتوبة
بإيدينا ومراجعة منك.

**القرارات (P4-1…P4-8، كلها الـ recommended):**
- **P4-1:** tool واحد للـ KPIs (`finance_kpi`) بـ `dataset` مقفول (weekly / category / customers / overdue / trend)، بدل 5
  tools (كل tool بياخد tokens في الـ prompt) أو `metric` حر (الموديل يألّف).
- **P4-2:** الـ audit = SQL views (migration 015) + تحقق مستقل في Python بـ `compute_toll`.
- **P4-3 (مهم جداً):** **الموظف بيتحقن من الكود، مش argument للموديل**. مفيش أي tool schema فيه `employee_id`، فالموديل
  مستحيل يسأل باسم حد تاني.
- **P4-4:** البحث في الأخبار = Tavily free tier (بـ `httpx`، من غير package جديدة). Brave اترفض (snippets بس).
- **P4-5:** نسخة الـ test ليها view توأم في `finance_test`، **مش جوه `finance`**.
- **P4-6:** الـ auditor بيشخّص السبب بـ checks ثابتة.
- **P4-7:** الأدوات الخارجية: timeout 10 ثواني، مفيش retry loop، أي فشل = `context_unavailable` **من غير أي رقم**
  ومبيتعملوش cache. اللي خلص من 14 يوم بيتعمله cache للأبد (علشان الـ replay يشوف نفس الـ context كل مرة).
- **P4-8:** الـ skill ≤ 1,200 token، والـ description ≤ 250 حرف.

**الـ 6 tools:**

| Tool | بيقرا منين | بيرجّع |
|---|---|---|
| `finance_kpi` | الـ KPI views | صفوف الـ view زي ما هي (نفس أرقام Power BI) + المصدر |
| `invoice_audit` | `finance.invoice_audit` (أو التوأم في test) | الـ findings + عدد الفواتير اللي اتراجعت + المبلغ المعرض للخطر |
| `compute_toll` | `toll_rate_bands` | الرسوم band بـ band (ADR-004) |
| `search_documents` | Qdrant (مكتبة الـ RAG) | passages بمصادرها، والصلاحيات جوه البحث |
| `suez_transits` | IMF PortWatch (public) | عبور السويس اليومي + متوسط 7 أيام |
| `web_search` | Tavily | ≤ 5 أخبار: **نص غير موثوق** |

**الـ contract الواحد:** كل tool = function `f(user, **args)` (تتختبر من غير LLM) + wrapper لـ LangChain بياخد الـ user
من الـ run context. النتيجة `ToolResult` فيها `status` (ok / not_permitted / context_unavailable / no_data)، والصفوف،
والـ `source` (الـ view والفلتر بالظبط). `not_permitted` مبيبقاش فيه ولا رقم ولا صف.

**الـ audit (migration 015):** بيعيد حساب كل فاتورة من الـ bands وبيطلّع findings:
- `duplicate_charge`: نفس المركب، ونفس اليوم، ونفس المبلغ.
- `tonnage_mismatch`: الـ SCNT في الفاتورة ≠ المركب.
- `amount_mismatch`: الفرق > قرش، ومعاه سبب محتمل يتجرب بالترتيب (`billed_on_invoice_tonnage`، `flat_terminal_rate`،
  `condition_swapped`، `sfu_priced_ballast`، وإلا `unexplained`).
- `rate_mismatch`.

**مفاجأة (D-P4-1):** الـ audit على الفواتير **الحقيقية** لقى **3 فواتير مكررة** فعلاً (نفس المركب ونفس اليوم ونفس المبلغ،
والنسختين مدفوعين): INV-0000626 (أسبوع 10)، 0000925 (15)، 0000630 (50)، بإجمالي 336,909 SDR. دي نتيجة السحب العشوائي
القديم. **القرار:** تفضل داتا (ADR-013)، واتقفلت كـ snapshot اتراجع، وبقت أول محتوى حقيقي لصفحة Exceptions.

**الـ Skills الـ 6** (كل واحد اتراجع منك واحد واحد، بـ 13 تصليح في المجموع):

| Skill | فيه إيه | أهم تصليح من مراجعتك |
|---|---|---|
| `finance-kpi-definitions` | تعريفات الـ KPIs | جملة الـ budget كانت غلط ("budget أعلى بـ 11%" والصح إن الفعلي أقل بـ 11%) |
| `suez-toll-audit` | إزاي يقرا finding، والإجراء لكل سبب | قواعد Notes الخاصة بالـ tariff = "manual review" مش "error" |
| `weekly-variance-analysis` | إزاي يطلّع الـ drivers (أكبر 3 تغييرات) | خطوة: شغّل `invoice_audit` قبل ما تسمي driver (ممكن يكون غلط فوترة) |
| `deck-style-guide` | شكل الـ 10 slides | slide 3 كان طالب رقم مفيش أي view بيرجّعه |
| `number-validation` | قواعد كتابة الأرقام | المثال الوحيد ("849.9 k") كان **غلطة الـ bake-off نفسها** |
| `untrusted-content` | النص المسترجع / الويب = داتا مش أوامر | أرقام NileGate من الحقول الـ structured بس، مش من نص passage |

**المشاكل وحلها:**
- **D-P4-3:** `invoice_audit` في الأول كان بيخلي الموديل يختار نسخة الـ test (اللي فيها الإجابات). الحل: الـ dataset بقى
  في الـ run context، والـ evaluation harness بس هو اللي يقدر يحطه `test`.
- **D-P4-2:** الـ permission classifier رفض تطبيق migration 015، فإنت طبّقتها بنفسك.
- **D-P4-6:** PortWatch بينشر متأخر أسبوع، فـ"خلص" = الفترة خلصت من 14 يوم.
- **باج في الاختبار:** حالة "مفيش key" كانت بتمسح المتغير، بس الـ tool بيقرا `.env` تاني فالـ key بيرجع. الحل: الاختبار
  بيحطه فاضي.
- **غلطة في skill اتكررت في اتنين.** الحل: `Tools_check.py` Phase 8 بقى بيتأكد إن **كل اسم مكتوب بين backticks في أي
  skill** موجود فعلاً في الـ tools، وبيعيد حساب أمثلة التقريب بـ Decimal.
- **حماية من injection:** `tools/trust.py` بيشغّل الـ screening على كل صف من مستند أو من الويب: بيشيل الحروف الخفية،
  وبيعلّم `suspected_injection`.

**النتيجة:** `Tools_check.py` 8 / 8 (بقى 10 / 10 بعدين):
- `compute_toll` = الـ 1,000 فاتورة.
- الـ audit مسك الـ 5 أخطاء المزروعة بأسبابهم و0 false alarms.
- matrix الصلاحيات: 100 موظف × 7 calls، تسريب = 0.

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `pipelines/agents/tools/context.py` | `RunContext` (الموظف + الـ dataset) + فحص الصلاحيات قبل أي query. |
| `pipelines/agents/tools/db.py` | connection pool قراءة بس على `PG_RO_USER`. |
| `pipelines/agents/tools/schemas.py` | `ToolResult` (Pydantic). |
| `pipelines/agents/tools/tariff.py` | `compute_toll`. |
| `pipelines/agents/tools/finance.py` | `finance_kpi` (وبعدين بيقرا التوائم في test). |
| `pipelines/agents/tools/audit.py` | `invoice_audit` + `totals()`. |
| `pipelines/agents/tools/documents.py` | wrapper لـ `search_documents`. |
| `pipelines/agents/tools/external.py` | `suez_transits` و`web_search` + الـ cache والـ timeout. |
| `pipelines/agents/tools/trust.py` | screening للنص غير الموثوق. |
| `pipelines/agents/tools/registry.py` | `STAGE1`: قايمة الـ tools اللي الـ graph بيربطها والـ matrix بيلف عليها. |
| `pipelines/agents/skill_loader.py` | يحمّل `SKILL.md` ويتأكد من الحجم والـ frontmatter. |
| `pipelines/agents/skills/<name>/SKILL.md` | الـ skills (6، وبعدين 7 مع `finance-qa`). |
| `db/migrations/015_invoice_audit_views.sql` | views الـ audit (live + test). |
| `pipelines/scripts/agents/Tools_check.py` | اختبار كل tool لوحده + الصلاحيات + الـ skills. |
| `Data/processed/agents/tool_cache/` | cache الأدوات الخارجية (git-ignored). |

---

### Phase 5 — الـ Workflow نفسه (2026-10-19) · ADR-050 · migration 016

**الهدف:** الـ graph الكامل: تقرير لأي أسبوع من الأول للآخر، **ويكمّل لو الجهاز وقع في النص**، ويقف يستنى موافقة إنسان.

**القرارات (P5-1…P5-8):**
- **P5-1 nodes هجين:** readiness و KPI و audit **كود** (مفيش سبب يبقوا LLM: أرخص وبيطلعوا نفس النتيجة كل مرة)، والـ
  Insight **agent** (LLM ⇄ tools لحد 4 لفات)، والـ Writer call واحدة structured. اترفض: agent لكل node (quota +
  reproducibility).
- **P5-2:** الـ Writer يطلّع `DeckDraft` (لسه مفيش PPTX)، والـ Validator أول نسخة: يرجّع للـ Writer مرتين بالكتير.
- **P5-3:** schema `agent_state` + role `agent_writer` بـ DML بس (من غير DDL). login `ports_agent` بيتعمل بسكربت، و
  `setup()` بيتشغل مرة واحدة كخطوة deployment بحساب الـ owner. **ليه؟** الـ login اللي شغال وقت الـ runtime مينفعش
  يقدر يعدّل الـ schema.
- **P5-4:** اللي يوافق لازم يبقى Finance manager أو الـ CEO (بيتشيّك في PostgreSQL وقت القرار). الـ edit بيرجع للـ
  Validator، والـ reject بيقفل الـ run، وكل قرار بيتسجل.
- **P5-5:** التقرير المتجدول بيشتغل باسم Finance manager، **مش الـ CEO** (أقل صلاحية: مفيش level 3).
- **P5-6:** إثبات الـ resume بقتل process حقيقية في النص.
- **P5-7:** الـ 52 أسبوع بـ fake models، والموديلات الحقيقية على 4 أسابيع بس.
- **P5-8:** قياس الـ tokens لكل call.

**اتبنت إزاي (S1→S7):**
- **S1:** `models.py` (الـ Pydantic outputs: `InsightNotes`، `DeckDraft`، `Verdict`، `ApprovalDecision`) و`roles.py`.
  قاعدة `roles.py` مهمة:
  - **availability → fallback:** الموديل مش متاح (quota، مفيش key، فشل متسجل)، فيروح للاحتياطي.
  - **validity → retry واحدة، وبعدها وقف:** الموديل رد بـ object غلط، فيتسأل تاني مرة واحدة على **نفس الموديل**، ولو غلط
    تاني الـ run يقف. **مفيش تبديل صامت** لموديل تاني يخبّي إن الأساسي بيغلط.
- **S2:** الـ nodes الثابتة. اختبار على الـ 52 أسبوع: كلهم ready، وموظف Operations بيقف عند البوابة من غير ولا رقم في
  الـ state.
- **S3:** الـ graph كله على `InMemorySaver`.
- **S4:** migration 016 + `create_agent_user.ps1` + `Checkpointer_setup.py` + `check_agent_user.py` (14 / 14). الـ assistant
  شغّل الـ 5 خطوات بموافقتك. نقطة كانت UNCERTAIN اتقفلت: الـ library بتعمل 4 جداول، كلهم جوه `agent_state`.
- **S5 (اختبار الوقوع):** process فرعية بتبدأ أسبوع 23 وبتعمل `os._exit(77)` **جوه الـ Writer** (زي ما الجهاز اتقفل فجأة).
  الـ process الأساسية (process تانية خالص) لقت الـ thread في PostgreSQL واقف قبل الـ writer، وكمّلت: writer → validator
  → approval بس (call LLM واحدة)، والنتيجة = تشغيلة من غير وقوع.
- **S6:** موديلات حقيقية على أسابيع 5 / 10 / 23 / 49 + الـ CLI `Weekly_pack.py`.

**المشاكل وحلها (أهم حاجة في الـ Phase):**
- **Groq رفض الـ prompts:** الـ prompts الحقيقية طلعت **9.7K–17K token**، وGroq المجاني حده 8K في الدقيقة، فرفض ("Request
  too large") وكل حاجة راحت للاحتياطي. **قرارك (ADR-045 amendment 1):** الـ Insight والـ Writer على `gemini-3.5-flash-lite`
  (250K في الدقيقة، ومتعادل مع qwen في الـ bake-off) + OpenRouter nemotron احتياطي. و"Request too large" بقى فشل ثابت
  متسجل (`too_large`)، فبيروح للاحتياطي على طول.
- **الموديل مكانش عارف يستشهد بنتايج الـ tools:** كتب `suez_transits` كـ evidence id، لأنه مبيشوفش الـ ids. الحل: فهرس
  evidence (id → tool + arguments) في الـ prompt.
- **D-P5-1: الـ Validator لقى ثغرة في نفسه:** كان بيشيل أي string فيه أرقام من الـ evidence كـ "identifier"، وده شال
  عناوين الأخبار، فـ"Canal revenue 7.5 M" من خبر عدّى. الحل: صفوف المستندات والويب **مبتديش أرقام خالص**.
- **تواريخ الأخبار** ("6 June 2025") كانت بتفشّل كل bullet في الـ context، والـ skill بيطلب تاريخ المصدر. الحل:
  `DATE_RE` بيشيل التواريخ (وفيه حالة اختبار بتثبت إن التاريخ مبيخبّيش مبلغ).
- **D-P5-6:** رد غلط مرتين = status اسمه `output_invalid` (مش exception)، لأن إعادة التشغيل هتقرا نفس الردود من الـ cache.
  أما خلص الـ quota فيفضل exception، علشان الـ thread يستنى ويكمّل بعدين.

**النتيجة:** 52 / 52 أسبوع بـ fake models وصلوا للموافقة واتنشروا. بالحقيقي: أسبوعين اتنشروا، وأسبوعين وقفهم الـ Validator
على **أخطاء حقيقية للـ Writer**: إشارة سالبة اتشالت جنب "down"، ونسبة متاخدة من dataset غلط. يعني الـ Validator اشتغل صح.
وأول تقرير حقيقي (أسبوع 10) وافق عليه الـ CEO واتحفظ في `reports/2025-W10/`.

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `pipelines/agents/graphs/weekly_pack.py` | الـ graph: الـ state، كل الـ nodes، `build_graph(roles, checkpointer)`. |
| `pipelines/agents/graphs/models.py` | الـ structured outputs (Pydantic، مستويين بالكتير علشان الـ free providers). |
| `pipelines/agents/roles.py` | مين يرد في كل دور (أساسي + احتياطي)، retry واحدة، `FakeRoles`. |
| `pipelines/agents/checkpointer.py` | PostgresSaver على `ports_agent` (مبيعملش `setup()` أبداً). |
| `db/migrations/016_agent_state.sql` | schema `agent_state` + role `agent_writer`. |
| `db/create_agent_user.ps1` / `db/check_agent_user.py` | يعمل الـ login ويختبر إنه DML بس. |
| `pipelines/scripts/agents/Checkpointer_setup.py` | خطوة الـ deployment (يرفض أي حساب غير postgres). |
| `pipelines/scripts/agents/Weekly_pack.py` | الـ CLI: `run` / `show` / `resume` / `list` (وفي Phase 8: `scheduled` / `prune` / `report`). |
| `pipelines/scripts/agents/Weekly_pack_check.py` | 7 phases: الـ roles، الـ nodes، 52 أسبوع، الـ Validator loop، الوقوع والـ resume، الموديلات الحقيقية، الـ contract. |
| `reports/2025-Www/` | التقارير المنشورة (git-ignored). |

---

### Phase 6 — الـ PowerPoint والـ Validator الحقيقي (2026-10-19) · ADR-051

**الهدف:** template بشكل NileGate، وWriter أحسن، وValidator **يمسك كل رقم غلط مزروع** (ده الـ done-when).

**المدخل (من Phase 5):**
- أخطاء الـ Writer كانت **إشارات جنب كلمات الاتجاه** و**evidence id غلط**، مش أرقام غلط.
- وثغرة الـ Validator: كان بيقبل الرقم لو يساوي **أي** حقل في الـ evidence، فرقم فئة تحت اسم فئة تانية بيعدّي.

**القرارات (P6-1…P6-8، كلها الـ recommended):**

| # | السؤال | اخترنا | البديل اللي اترفض وليه |
|---|---|---|---|
| P6-1 | الأرقام تدخل النص إزاي | **slots:** `{kpi.weekly:billed_wow_pct\|%1}`، والكود يحط الرقم | نص حر + الموديل يعلن الحقل (الموديلات المجانية بتملا الـ schema ده وحش)؛ الـ Validator يخمّن الحقل (هي دي الثغرة) |
| P6-2 | مين يكتب إيه | **الكود:** slide 1، الكروت، كل الجداول والـ charts، الـ footnotes، slide 10. **الـ Writer:** العناوين، 5 bullets للملخص، ≤ 3 تعليقات، الـ context | الـ Writer يكتب كل حاجة |
| P6-3 | السالب يتكتب إزاي | **الكود يكتب الاتجاه** (`\|dir` → "down 30.8 %") | رقم بإشارة دايماً |
| P6-4 | الـ charts | **native PowerPoint charts** (قيمها تتقري تاني) | صور matplotlib (الـ Validator مش هيعرف يقراها) |
| P6-5 | الـ template | **كود** (`style.py`) | تصمّمه إنت في PowerPoint الأول (وقتك؛ ممكن يحل محله بعدين) |
| P6-6 | إعادة الكتابة | **patch:** الـ bullets الغلط بس + مشاكلها | الـ deck كله تاني (tokens + ممكن يبوّظ الصح) |
| P6-7 | الملف نفسه | **الـ Validator يقرا الـ PPTX تاني** (V8) | نثق في الـ renderer |
| P6-8 | الـ done-when | **اختبار الأرقام المزروعة** (100%)، والحقيقي reported | gate على 4 / 4 أسابيع حقيقية |

**الـ Validator v2 (القواعد V1–V8):**
- **V1:** كل bullet فيه رقم بيستشهد بـ evidence موجود من tool structured.
- **V2:** الـ slots سليمة (الـ evidence موجود، والصف واحد بس، والحقل موجود ورقمي، والـ format مسموح)، و**الرقم الحرفي**
  (من edit إنسان مثلاً) لازم يرتبط بحقل في صف الجملة **بتسميه**.
- **V3:** العنوان فيه "Draft for approval".
- **V4:** شكل الـ deck: 10 عناوين، و5 bullets للملخص، و≤ 3 تعليقات.
- **V5:** كل slide يستشهد بس بالـ evidence المسموح له (slide 9 = context خارجي بس).
- **V6:** كلمة الاتجاه (up / down / rose / fell / above / below) لازم تتفق مع إشارة الرقم.
- **V7:** الـ attribution:
  - الفئة اللي اتسمّت driver لازم تبقى من أكبر 3.
  - كل فاتورة اتذكرت لازم تبقى موجودة.
  - الـ slot لازم يبقى تحت كلمة من عيلة الحقل بتاعه.
  - إجمالي الأسبوع ميتحطش على فاتورة واحدة.
- **V8:** الملف نفسه بيتفتح تاني. كل shape ليه اسم contract (`tpl:` / `bind:` / `txt:` / `tbl:` / `chart:` / `deco:`)،
  وكل نص وكل خلية وكل نقطة في chart بتتقارن. يعني لو حد غيّر رقم في الملف نفسه، بيتمسك.

**اتبنت إزاي:** S1 `slots.py` → S2 الـ Validator → S3 الـ style والـ render والـ readback (V8) → S4 الـ Writer prompt
و`DeckPatch` والـ graph → S5 الـ skills اتكتبت تاني وإنت راجعتها → S6 موديلات حقيقية (5 تشغيلات).

**المشاكل وحلها:**
- **D-P6-1:** أسماء الفئات فيها "/" ("Roll-On/Roll-Off (Ro/Ro) Vessels")، فالـ key عمره ما بيتقسم على "/".
- **D-P6-8:** مفيش 13 لون للفئات، لأن قواعد الـ dataviz بتحدد 8. الحل: billed أزرق و budget رمادي في كل حتة.
- **D-P6-9:** `reverse_order` في python-pptx كان بيطلّع المحور فوق، فالـ bars بقت بتترسم من الأصغر للأكبر.
- **5 تشغيلات حقيقية**، وكل واحدة علّمتنا حاجة واتحولت لحالة اختبار:
  - **Run 1** (1 / 4): اكتشفنا false alarm ("DSO window billed amount")، والـ patches فشلت لأن الرسائل مكانتش بتقول **تكتب
    إيه**. الحل: كل رسالة بقت تقول الحل في سطر.
  - **Run 2** (3 / 4): أسبوع 10 حط رقم NileGate في slide 9 (الـ context). الحل: رسالة أوضح.
  - **Run 3** (1 / 4): 3 false alarms للـ Validator على جمل صح. الحل: قواعد الـ context اتظبطت.
  - **Run 4** (4 / 4)، بس لما بصينا على الـ PNG: "up up 25.8 %" وslide 1 كاتب "Draft for approval" في نسخة approved. الحل:
    قواعد جديدة.
  - **Run 5** (3 / 4): الأسبوع اللي وقف كان غلطة حقيقية للـ Writer ("days days").
- **قرارك:** نسيبها 3 / 4 ونقفل. **ليه؟** نفس الـ prompt بيطلّع 3 / 4 / 3 في تشغيلات مختلفة (تفاوت الموديل)، وكل فشل من
  run 3 لحد آخر run كان غلطة حقيقية.

**النتيجة:** `Deck_check.py` **4 / 4**:
- **100 / 100 رقم غلط مزروع اتمسكوا بالقاعدة الصح**: 17 نوع في الـ draft + 8 أنواع في الملف × 4 أسابيع.
- 0 false alarms على 52 deck نضيف.
- الـ Writer calls نزلت لـ ≤ 12.4K token (كانت 17K)، والـ patch ≈ 20% من حجم أول draft.

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `pipelines/agents/deck/slots.py` | لغة الـ slots: `find_slots`، `resolve`، `format_value`، `normalize_text` (من Phase 7)، الاتجاه بالعربي. |
| `pipelines/agents/deck/validator.py` | V1–V7 + `check_text` + `render_draft`. |
| `pipelines/agents/deck/style.py` | الألوان والخطوط والمقاسات (16:9، navy / teal). |
| `pipelines/agents/deck/render.py` | يرسم الـ 10 slides (كل عنصر باسم contract). |
| `pipelines/agents/deck/readback.py` | يقرا الـ PPTX تاني (V8). |
| `pipelines/agents/deck/sample.py` | draft صح محسوب (للاختبارات بس: الـ fake Writer والأساس اللي بنزرع فيه الأخطاء). |
| `pipelines/scripts/agents/Deck_check.py` | 4 phases: الـ slots، الـ 52 deck، الأرقام المزروعة، الأخطاء المتسجلة من التشغيلات الحقيقية. |

---

### Phase 7 — التقييم (2026-10-19 → 10-22) · ADR-052 / ADR-053 · migration 017

**الهدف:** نقيس الـ agents على حاجة متعرفة الإجابة: أسابيع ذهبية وأسئلة مالية ذهبية، بقواعد مقفولة قبل أي تشغيل.

**القرارات:**
- **مراجعة §8a (G1–G6):**
  - **G1:** صحة الاتجاه والـ attribution.
  - **G2:** ~10 أسئلة بالعامية المصري، والحد AR ≥ EN − 0.10.
  - **G3:** الرفض الصح لما الإجابة مش موجودة.
  - **G4:** الاكتمال بقواعد ثابتة، **من غير LLM judge**.
  - **G5:** الـ edits البشرية reported بس.
  - **G6:** هامش 0.03 وتجربتين.
- **P7-1:** agent صغير للـ Q&A المالي. **P7-2:** الـ budget miss من views توأم (migration 017). **P7-3:** `InMemorySaver` للتقييم.
  **P7-4:** فولدر مؤقت لكل تشغيلة.
- **ADR-052 اتكتب قبل أول مقارنة** (زي ما عملنا في الـ RAG): تجربتين لكل setup، والـ hard gates متتكسرش، والـ primaries
  (narrative recall وQ&A completeness) متقعش أكتر من 0.03.

**اتبنت إزاي:**
- **S1:** `Golden_weeks.py` اختار 11 أسبوع **بقواعد**:
  - **test:** 10 / 23 / 36 / 49.
  - **live:** 5 (warm-up)، 48 (الذروة)، 41 (أهدى أسبوع)، 16 (أقل أسبوع)، 47 (أكبر budget miss حقيقي −47%)، 15 (فاتورة
    مكررة حقيقية)، 24 (أكبر حركة في السويس).
  - الأسابيع الـ 4 اللي ظبطنا عليها في Phase 6 بتتقاس لوحدها (seen مقابل unseen).
  - 34 finding متوقع اتكتبوا بالإيد وإنت وافقت عليهم.
- **S2:** migration 017 (`finance_test.kpi_weekly` و`kpi_weekly_category`: فوترة وbudget من النسخة، والـ receivables من
  الـ live).
- **S3:** `Qa_golden.py`: 40 سؤال (30 EN: 22 ليهم إجابة + CEO control + 4 abstention + 3 رفض صلاحيات، و10 بالعامية).
- **S4:** `finance_qa.py` (الـ agent) + skill `finance-qa`.
- **S5:** `Stage1_eval.py`:
  - Phase 1: الـ hashes.
  - Phase 2: **كل scorer اتثبت إنه بيمسك الغلط بتاعه على حالات معمولة بالإيد** (scorer عمره ما فشل ميثبتش حاجة).
  - Phase 3–4: fake models.
  - Phase 5: الحقيقي.
- **S6:** التشغيلات الحقيقية.

**المشاكل والاكتشافات:**
- **D-P7-1: الـ budget miss المزروع طلع مش miss:** الـ generator رفع budget أكبر فئة في الأسبوع (LNG) × 1.5، بس LNG كانت
  أصلاً فوق الـ budget بـ 106%، فبقت فوقه بـ 37%. في الأول اتشال من الـ gate (5 / 5)، وفي §5f اتعمل صح (migration 018).
- **D-P7-11: flash-lite حده 500 request في اليوم** (الـ 429 قالها). الـ baseline (≈ 380 call) + أول c1 خلّصوه، والباقي راح
  للـ OpenRouter (بطيء، وموديلات مخلوطة، فالنتيجة متتقارنش). **الحل:** تقييم كامل واحد في اليوم، والـ harness **يقف لما
  quota الأساسي يخلص** بدل ما يكمّل على الاحتياطي.
- **التشغيلات (كل واحدة اتنين runs):**

| التشغيلة | النتيجة | ليه |
|---|---|---|
| baseline (10-19) | D7 مش متحقق؛ planted 2 / 5، 1 / 5 | أخطاء Writer حقيقية + 3 false alarms للـ Validator ("week 48" اتقرت رقم) |
| **c1** (10-20) | **اتقبل** (planted 5 / 5، recall +0.10) | تصليح الـ false alarms + سطور prompt للـ Q&A |
| c2 (10-21) | **اترفض** (planted وقع لـ 1 / 5) | الـ abstention بقى 1.0، بس test weeks 10 / 23 مااتنشروش |
| c3 (10-22) | اترفض بالهامش بس (AR −0.05) ثم **اتقبل باستثناء منك** | كل الـ gates ثابتة، recall 0.88، والوقوع كله من جملة عربي واحدة فيها رقم من اسم مركب |

- **D-P7-14 (ADR-051 amendment 1):** `normalize_text` بيصلّح **شكل** الـ slot قبل الـ Validator: format مش مسموح يرجع
  للـ default، و`[row]` على نتيجة صف واحد بيتشال، و"SDR SDR" / "days days" يتشال المكرر. **الأرقام عمرها ما بتتلمس.** ده
  كان السبب المتكرر لوقوف الـ packs.
- **D-P7-15:** الـ Q&A checker بقى يسمح برقم جوه نص الـ tool نفسه (اسم مركب، صفحة)، والـ slot evidence id بيتضاف للـ
  bullet لو الـ Writer نسيه.

**قرارك في الآخر:** "اقبل c3 ووقف التظبيط". Phase 7 اتقفلت وD7 مش متحقق بـ slot واحد.

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `pipelines/scripts/agents/Golden_weeks.py` | يختار الأسابيع بقواعد ويقفل الـ evidence المتوقع. |
| `pipelines/scripts/agents/Qa_golden.py` | يبني ويقفل الأسئلة الذهبية بالقيم المتوقعة. |
| `pipelines/scripts/agents/Stage1_eval.py` | الـ harness: الـ scorers، الـ gates، الـ ADR-052، ملف النتيجة. |
| `pipelines/agents/graphs/finance_qa.py` | الـ agent بتاع الـ Q&A (بقى على `create_agent` في §5f). |
| `pipelines/agents/skills/finance-qa/SKILL.md` | شكل الإجابة، الـ slots، الرفض، المصادر. |
| `db/migrations/017_finance_test_kpi.sql` | الـ views التوأم. |
| `Data/processed/agents/eval/golden_weeks.json` / `golden_weeks_expected.json` / `golden_findings.json` / `finance_qa_golden.jsonl` | المدخلات المقفولة بـ hash. |
| `Data/processed/agents/eval/stage1_eval_*.json` | نتيجة كل تشغيلة (baseline، c1، c2، c3، confirm). |
| `Data/processed/agents/eval/llm_cache/eval_<tag>_r<k>/` | cache منفصل لكل run علشان الـ run التاني يبقى calls جديدة (git-ignored). |

---

### Phase 8 — التشغيل لوحده + المتابعة + التنضيف (2026-10-20 → 10-22) · ADR-054

**الهدف:** Task Scheduler يشغّل التقرير ويستنى الموافقة، و`agent_state` ميكبرش للأبد من غير ما نخسر سجل الموافقات، وكل
تشغيلة تبان في LangSmith.

**القرارات (P8-1…P8-4):**
- **P8-1 أنهي أسبوع:** الأسبوع اللي بعد آخر أسبوع "خلص" في الـ replay، و**pack واحد مستني في المرة**. يعني لو فيه
  تقرير مستني موافقتك، التشغيلة مبتبدأش حاجة وتكتب "wait". اترفض: رقم أسبوع النهارده (بيقفز وفيه فجوات).
- **P8-2 إمتى:** كل اتنين 10:30 (بعد ما quota Gemini يتجدد)، **وإنت عامل logon بس** (من غير باسورد Windows متخزن)،
  ولو اتفوّت يشتغل أول ما يقدر، ولو فشل يعيد مرتين كل 30 دقيقة، وحد ساعة، وlog + toast.
- **P8-3 التنضيف:** الـ thread اللي **خلص** وعدّى عليه 30 يوم: يتسجل في `threads_archive.jsonl` الأول وبعدين
  `delete_thread`. **الـ thread المستني عمره ما بيتمسح.**
- **P8-4 المتابعة:** LangSmith على أوامر التشغيل بس (`run` / `resume` / `scheduled`)، **مش في الـ checks ولا التقييم**
  (التقييم ≈ 400 call هيخلّص الـ free allowance)، ومن غير المفتاح العام `LANGSMITH_TRACING` أبداً.

**الـ Deviations والمشاكل:**
- **D-P8-1:** thread وقف في النص (quota أو 503) بيكمّل في التشغيلة الجاية قبل أي حاجة جديدة.
- **D-P8-2:** الـ reject = محاولة خلصت من غير deck، فبتتعاد مرة، وبعدين الأسبوع يتعدّى.
- **D-P8-3:** إعادة المحاولة في Task Scheduler مبتشتغلش على exit code الـ action (بتشتغل بس لو الـ task نفسه فشل يبدأ).
  الحل: التشغيلة **بتستنى PostgreSQL بنفسها** (كل 60 ثانية لحد 30 دقيقة)، لأن Docker Desktop بيقوم بعد الـ logon.
- **D-P8-4:** lock file بالإضافة لـ "متشغلش نسختين".
- **D-P8-5:** الـ tracing = context حوالين كل graph run، مش متغير بيئة. **ليه؟** علشان التقييم والـ checks ميتعملهمش
  trace من غير ما نعدّل فيهم.
- **D-P8-8:** أول قراءة من LangSmith طلّعت `trigger: scheduled` بدل القيمة الصح، لأن الـ metadata بتاعة الـ graph config
  بتكسب لو المفتاح مشترك. الحل: مفتاح الـ tracer اسمه `launched_by` (مختلف).
- **D-P8-10:** الـ fallback (nemotron-3-super) بيرجّع 404 على كل request، فبقى مكسور. اتقفل في §5f F7.
- **D-P8-12:** read-back بتاع LangSmith فشل مرة لأن الـ root run وصل قبل الـ children. الحل: يستنى الـ children كمان.

**التجربة الحقيقية (الـ done-when):** 3 تشغيلات بـ `Start-ScheduledTask`:
- **التشغيلة 1:** Gemini رجّع 503 "high demand" في الـ Insight، والـ fallback رجّع 404، فخرجت بـ exit 1 والـ thread
  استنى عند الـ checkpoint بتاعه.
- **التشغيلة 2:** نفس الكلام.
- **التشغيلة 3 (بعد 30 دقيقة):** **كمّلت W11 من الـ checkpoint ووصلت للموافقة**: الـ Validator عدّاها، والـ preview
  اتعمل، والـ toast ظهر، وexit 0، والتشغيلة باينة في LangSmith.

بعد كده، بأمرك، الـ assistant قرر في W11: Finance manager **7** (مش 6 اللي اتعمل باسمه التقرير) عدّل جملة واحدة ووافق،
والتقرير اتنشر. **أول G5:** edit rate = 0.5 على W10 + W11.

**الملفات:**

| الملف | بيعمل إيه |
|---|---|
| `pipelines/agents/scheduling.py` | `plan` (أنهي أسبوع)، `fire` (تشغيلة متجدولة واحدة)، `prune` (أرشيف ثم مسح)، `approval_report` (G5)، `toast`. |
| `pipelines/agents/tracing.py` | `trace(...)`: LangSmith جوه context بس، ولو فيه key بس، وفشله ميوقعش التشغيلة. |
| `ops/scheduler/register_weekly_pack.ps1` | يسجّل الـ task في Windows (أو `-Unregister`). |
| `pipelines/scripts/agents/Scheduler_check.py` | 6 phases: اختيار الأسبوع، pack واحد في المرة، التنضيف، الـ tracing، قراءة trace حقيقي من LangSmith. |
| `reports/_log/scheduled.jsonl` / `threads_archive.jsonl` / `scheduled_console.log` | سجل كل تشغيلة + أرشيف الـ threads اللي اتمسحت. |
| `.env`: `PACK_RUN_AS=6`، `LANGSMITH_API_KEY` | باسم مين بيشتغل التقرير + مفتاح المتابعة. |

---

### §5f — قفل Phases 7–8 من غير ولا نقطة مفتوحة (2026-10-22 → 10-23)

**الهدف:** إنت طلبت إن قبل الـ commit والـ checkpoint **مفيش ولا نقطة "مؤجلة" أو مش واضحة**. اتعمل جرد (K1–K9)
وإنت قررت إزاي تتقفل كل واحدة (C-1…C-4)، والترتيب F1…F9.

| # | النقطة المفتوحة | اتقفلت إزاي |
|---|---|---|
| K1 | مراجعتك لـ D-P7-1…D-P7-15 والـ skill والأسئلة الذهبية | **C-1:** واحدة واحدة في الشات: 18 نقطة، 13 اتقبلت و5 اتغيرت |
| K2 | D-P7-15 متقاسش بالحقيقي، وD7 ناقص slot | **C-2:** تقييم تأكيد واحد (F8) = الـ baseline النهائي |
| K3 | الـ fallback مكسور | **C-3:** fallback مجاني جديد (F7) |
| K4 | صفحة Exceptions فاضية | **C-4:** تتبني (F6) |
| K5 | قواعد Notes في الـ tariff مش متطبقة | **C-4:** migration 019 (F5) |
| K6 | مفيش CLI للـ Q&A | `Finance_qa.py` (F2) |
| K7 | `list_runs` في LangSmith هيتشال بعد 2027-01-31 | البديل async بس، فاتسابت والسبب مكتوب في الـ check (F1) |
| K8 | الـ CLI بيطبع `reason` فاضي بدل الـ comment | اتصلّح (F1) |
| K9 | "Tavily خلص" | probe أثبت إنه 40 / 1,000 بس (كلام قديم) |

**الـ 5 حاجات اللي اتغيرت من مراجعتك (K1):**
- **D-P7-1 → budget miss حقيقي:** أسبوع 36، budget الـ LNG = فوترتها × 1.5 (−33.3%)، بـ **migration 018**. اتعدّل
  الـ generator، والـ findings بقت v3، والـ gate بقى `planted_all` = 6 / 6.
- **D-P7-3 → اتنين سائلين لكل profile:** Finance employee 13 + 24، Operations employee 12 + 17، Operations manager 2 + 3، و
  الـ CEO لوحده.
- **D-P7-4 → سؤال زيادة:** Finance employee بيسأل على إيرادات HbR (level 3)، فلازم يترفض من غير تسريب.
- **D-P7-6 → الـ Q&A على `create_agent` بتاع LangChain** مع middleware، وموديله adapter فوق `llm.py`، فقواعد الـ cache
  والـ quota والـ fallback فاضلة زي ما هي.
- **D-P7-7 → check منفصل:** `Finance_qa_check.py`.

**F1–F9:**
- **F1 كود صغير:**
  - `show` بيطبع الـ comment.
  - كل تصليح شكل slot بالكود بيتسجل في `run.json` وفي `report` (`form_fixes`)، علشان أخطاء الموديل تفضل باينة. W11 كان فيه 5.
  - الـ `list_runs` اتساب والسبب مكتوب.
- **F2:** `finance_qa.py` اتبنى تاني على `create_agent`:
  - `RoleChatModel` = `BaseChatModel` فوق `roles.py`.
  - middleware `QaTurn` بيحط تعليمات الإجابة في كل request، ويشيل الـ tools بعد 3 لفات، ويعمل check + patch واحد.
  - `ModelCallLimitMiddleware(8)`.
  - `Finance_qa_check.py` 6 / 6، ولقى باج حقيقي واتصلّح.
  - CLI جديد: `Finance_qa.py ask "…" --as E [--lang ar]`.
- **F3:** migration 018 + الـ generator + إعادة قفل الـ evidence (`REFREEZE`: انتقال واحد متسجل بالـ hash القديم والسبب).
- **F4:** الأسئلة الذهبية v2 = 42 (32 EN + 10 AR). كلمات الـ scorer اتصلحت **بقاعدة مش من نتيجة**: "category / vessel
  category"، و«فاتور» / «فوتنا»، و"940,355 thousand".
- **F5 (migration 019):**
  - قريت قواعد Notes في الـ corpus بتاعنا وقارنتها بالـ bands.
  - ballast Petroleum Product طلع **موجود أصلاً** في الجداول.
  - ballast "Oil/Chemical" مختلف، والفئة بتاعتنا أوسع، فمينفعش نعرف النوع الفرعي. علشان كده اتضاف عمود `review`
    (`error` | `manual_review`)، والـ manual review عمره ما بيتحسب flagged أو "معرّض للخطر".
- **F6 صفحة Exceptions:**
  - جدول `Invoice Audit` (DirectQuery) + relationship + 3 measures (`Audit Findings`، `Invoices Flagged`، `Invoices Manual Review`).
  - كارت + جدول findings + ملاحظة.
  - الأرقام اتراجعت بـ DAX على 5 أسابيع.
  - الشكل على الشاشة إنت اللي هتبص عليه.
- **F7 الـ fallback الجديد:**
  - 16 موديل مجاني فيهم tools و≥ 32K context. اتعملهم smoke test، وعدّى اتنين (`dots-3-note-preview` و
    `nemotron-3.5-super-vl`).
  - pack متجبر على كل واحد فيهم: dots 0 / 2، و**nemotron-3.5-super-vl 1 / 2** فهو اللي اتختار (ADR-045 amendment 2).
  - fallback جزئي: لو وقع، الـ thread بيستنى التشغيلة الجاية زي ما كان.
  - (سيشن تانية عملت نفس التجربة في نفس الوقت ووصلت لنفس القرار، واتأكدنا إن مفيش conflict.)
- **F8 تقييم التأكيد** (2026-10-23، 290 call، 0 fallbacks) = **الـ baseline النهائي** `stage1_eval_2026-10-23_confirm.json`.
  التفاصيل في القسم 4.
- **F9:** الـ ADRs و ARCHITECTURE و ROADMAP و CLAUDE.md اتحدثوا، وكل الـ checks اتشغلت ونجحت، وأمر commit واحد،
  وقرارات Phase 9 اتجاوبت.

**اكتشاف أثناء F8 (D-P8-16):**
- الـ false alarms اللي ظهرت (0.33 و0.25) كانت **غلطة في الـ scorer**: كان بيعد كل رقم فاتورة في جملة فيها كلمة خطأ،
  فالفاتورة **الأصلية** المذكورة جنب الـ duplicate ("INV-9000292 duplicate of INV-0000292") بقت alarm.
- الجملتين كانوا صح، يعني الـ false alarms الحقيقية = **صفر**.
- الـ scorer اتصلّح بقاعدة + حالتين اختبار، وملف النتيجة اتساب زي ما اتحسب.

**الملفات الجديدة في §5f:** `db/migrations/018_finance_test_budget_miss.sql`، `019_invoice_audit_notes_rule.sql`،
`Data/processed/synthetic/finance/finance_test_budget_v2.csv`، `Data/processed/agents/eval/finance_test_answer_key_v2.json`،
`pipelines/scripts/agents/Finance_qa.py`، `Finance_qa_check.py`، `pipelines/checkpoints/agents/Finance_qa_check.md`،
`powerbi/…/tables/Invoice Audit.tmdl`.

---

## 4. النتيجة النهائية لـ Stage 1 (تقييم التأكيد، 2026-10-23)

| المقياس | Run 1 | Run 2 | المطلوب (D7) | اتحقق؟ |
|---|---|---|---|---|
| أرقام الـ deck صح | 100% | 100% | 100% | ✅ |
| الأخطاء المزروعة اتمسكت | 2 / 6 | 3 / 6 | كلها | ❌ |
| False alarms (الحقيقية بعد تصليح الـ scorer) | 0 | 0 | ≤ 5% | ✅ |
| الـ claims صح (اتجاه + drivers) | 100% | 100% | 100% | ✅ |
| كل رقم ليه مصدر (traceability) | 100% | 100% | 100% | ✅ (الـ slot اللي كان ناقص في c3 اتصلّح) |
| تسريب صلاحيات | 0 | 0 | 0 | ✅ |
| الرفض الصح (abstention) | 1.0 | 1.0 | 100% | ✅ |
| تقارير اتنشرت | 7 / 11 | 10 / 11 | (reported) | |
| Narrative recall | 0.66 | 0.93 | primary (المتوسط 0.79) | |
| Q&A إنجليزي / عربي | 0.96 / 1.0 | 0.96 / 0.90 | AR ≥ EN − 0.10 | ✅ |

**الخلاصة بصراحة:**
- **D7 مش متحقق في gate واحد بس:** الأخطاء المزروعة.
- **السبب:** لما الـ Validator يوقف تقرير أسبوع test، التقرير ده ملوش deck، فالأخطاء اللي فيه بتتحسب "اتفوّتت". ده حصل 3
  مرات، ومرة رابعة التقرير اتنشر بس ماقالش إن LNG أقل من الـ budget.
- **الحاجة الكويسة:** ولا تقرير غلط اتنشر خالص. الأمان شغال، والتمن إن بعض التقارير بتقف.
- **التحسين الجاي (follow-up، مش gate):** نسبة النشر بتاعة الـ Writer على الموديل المجاني.

---

## 5. خريطة كل ملفات Stage 1

```text
pipelines/agents/
  llm.py                 البوابة لأي LLM: cache، quota، أخطاء
  roles.py               مين يرد في كل دور + fallback + retry واحدة + FakeRoles
  checkpointer.py        PostgresSaver على agent_state
  skill_loader.py        تحميل SKILL.md
  scheduling.py          التشغيل المتجدول، التنضيف، تقرير G5
  tracing.py             LangSmith حوالين كل run
  tools/                 context, db, schemas, tariff, finance, audit, documents, external, trust, registry
  skills/                7 skills (6 لـ الـ pack + finance-qa)
  graphs/                weekly_pack.py (الـ graph)، finance_qa.py (الـ Q&A)، models.py (Pydantic)
  deck/                  slots, validator, style, render, readback, sample

pipelines/scripts/agents/
  LLM_smoke_test.py, LLM_bakeoff.py                    Phase 0
  Tools_check.py                                        Phase 4 (10 / 10)
  Checkpointer_setup.py, Weekly_pack.py, Weekly_pack_check.py   Phase 5 (7 / 7)
  Deck_check.py                                         Phase 6 (4 / 4)
  Golden_weeks.py, Qa_golden.py, Stage1_eval.py         Phase 7
  Scheduler_check.py                                    Phase 8 (6 / 6)
  Finance_qa.py, Finance_qa_check.py                    §5f (6 / 6)

pipelines/scripts/synthetic/Finance_generator.py       Phase 1
pipelines/scripts/finance/Finance_views_check.py       Phase 2
pipelines/checkpoints/agents/*.md                       قصة كل check خطوة خطوة

db/migrations/012 … 019                                الداتا، الـ views، الـ trend، الـ audit، agent_state، التوائم، الـ budget miss، قاعدة Notes
db/create_finance_bi_user.ps1, check_finance_bi_user.py    login الـ Power BI
db/create_agent_user.ps1, check_agent_user.py              login الـ agents
db/verify_readonly.sql §17–§23                             الـ audits
db/audit/2026-10-*_after_0NN_report.txt                    نتيجة كل audit

powerbi/NileGate_Finance.pbip                           الـ dashboard (13 جدول، 41 measure، 19 relationship، 5 صفحات)
ops/scheduler/register_weekly_pack.ps1                  تسجيل الـ task في Windows

Data/processed/synthetic/finance/                       الـ CSVs المتولدة + manifest
Data/processed/agents/eval/                             المهام والأسئلة والأسابيع المقفولة + كل نتايج التقييم
Data/processed/agents/eval/llm_cache/                   كل رد LLM (git-ignored)
Data/processed/agents/tool_cache/                       cache الأدوات الخارجية (git-ignored)
reports/                                                التقارير المنشورة + الـ logs (git-ignored)

docs/finance_metrics.md                                 تعريف كل KPI
docs/decisions.md  ADR-045 … ADR-054                    القرارات
docs/plans/Agents_plan.md                               الخطة + Progress بكل يوم
```

---

## 6. الدروس الكبيرة اللي طلعنا بيها

1. **الـ LLM ميكتبش أرقام.** الـ slots حلّت مشكلة كانت بتتكرر في كل موديل جربناه، حتى الأكبر.
2. **الـ Validator لازم يبقى كود ويتختبر بأخطاء مزروعة.** 100 / 100 مش صدفة: كل false alarm أو غلطة فاتت في تشغيلة
   حقيقية اتحولت لحالة اختبار ثابتة.
3. **الحدود المجانية بتغيّر التصميم:** حد Groq في الدقيقة (8K) شال qwen من الـ pack، وحد flash-lite اليومي (500) حدد إن فيه
   تقييم واحد في اليوم، والـ fallback ممكن يختفي في أي يوم (nemotron-3-super).
4. **التقييم يتقفل قبل التشغيل.** الأسابيع والأسئلة والـ findings اتقفلت بـ hash، وأي تغيير بيعدي بانتقال متسجل
   (`REFREEZE`).
5. **تفاوت الموديل حقيقي:** نفس الـ prompt بيطلّع 3 / 4 / 3. علشان كده ADR-052 بيطلب تجربتين.
6. **الـ scorer نفسه ممكن يغلط** (D-P8-16)، علشان كده كل scorer بيتختبر بحالات معمولة بالإيد، ولما يغلط بيتصلّح بقاعدة مش
   بالنتيجة.
7. **الصلاحيات من الكود مش من الموديل:** مفيش tool schema فيه موظف أو dataset. علشان كده التسريب = 0 في كل تشغيلة.

---

## 7. اللي جاي

- **دلوقتي:** الـ PR بتاع Stage 1 checkpoint (`feat/agents` → `master`).
- **Stage 2 — Operations Desk:**
  - **Phase 9:** الـ tools (`sea_route`، `voyage_status`، `marine_weather`، جدول parameters المراكب).
  - **Phase 10:** route advice.
  - **Phase 11:** voyage watch.
  - **Phase 12:** الـ Supervisor على المنتجين.
- **قرارات Phase 9 اتجاوبت (2026-10-23):**
  - **من غير live AIS.**
  - الباقي الـ recommended: CSV + migration، سعر VLSFO بتاريخه، searoute restrictions، alerts متجدولة، ETA rule-based
    الأول، والـ thresholds زي المقترح.

</div>
