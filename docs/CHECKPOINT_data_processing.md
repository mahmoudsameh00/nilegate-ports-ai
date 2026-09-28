# Checkpoint — Data processing مقفولة (2026-09-27)

ملخص بسيط لكل اللي اتعمل في معالجة الداتا، عشان تبدأ منه مرحلة الـ RAG. التفاصيل الكاملة في
`ARCHITECTURE.md` و`docs/decisions.md` (ADR-027 لحد ADR-035).

---

## 1. الداتا اللي عندنا — 3 أنواع

| النوع | فين | إيه هي | راحت فين |
|---|---|---|---|
| **Structured** | `Data/raw/structured/` | موانئ حقيقية (UN/LOCODE) + شبكة الخطوط بينها + تعريفة قناة السويس | PostgreSQL |
| **Synthetic** (مولّدة) | `Notebooks/synthetic/` | موظفين وسفن وcontainers وفواتير للشركة الوهمية NileGate | PostgreSQL |
| **Semi-structured** | `Data/raw/semi-structured/` | **AIS** (إشارات السفن: مين، فين، بسرعة كام) + **EDI** (رسايل تعليمات شحن بصيغة EDIFACT) | MongoDB |
| **Unstructured** | `Data/raw/unstructured/` | 29 ملف PDF (تقارير البنك الدولي، الموانئ، IMO، السويس، 23 تقرير حوادث USCG) | chunks جاهزة للـ RAG |

---

## 2. الـ semi-structured: عملنا إيه وليه

**الـ raw كانت:**
- `AISHub sample.json`: لقطة 30 دقيقة لـ 10,000 سفينة حقيقية، سجل واحد لكل سفينة، يعني **مفيش رحلات**.
- `NOAA AccessAIS.csv`: 54 سفينة لمدة 78 دقيقة **جوه ميناء** Los Angeles.
- `IFTMIN_D12A_sample.edi`: رسالة EDI واحدة. هي نفسها بتقول إنها "synthetic sample"، وفيها غلطة في العدّاد.

**الخطوات:**

1. **Profiling قبل التصميم** (`AIS_EDI_profiling.ipynb`). اكتشفنا:
   - كل القيم نصوص، وأرقام IMO كتير وهمية (`0` و`1234567`).
   - قيم زي 511 و102.3 معناها "مش متاح".
   - إشارتين بفرق ثواني بيدّوا سرعة 300 عقدة (شوشرة GPS).

   **ليه؟** لو صممنا على الافتراضات، كنا هنرفض داتا سليمة أو نقبل داتا بايظة.
2. **MMSI في PostgreSQL.** الـ AIS بيعرّف السفينة بالـ MMSI، وجدول `vessels` مكانش فيه. ضفناه، وأول 3 أرقام منه جاية من **جدول ITU الرسمي** حسب علم الدولة.
   - PostgreSQL هو **المرجع** لهوية سفننا.
   - السفن الحقيقية في العيّنات مش سفننا، ومش مربوطة بيها.
3. **MongoDB في Docker** (`ports-mongo`): على جهازك بس، وuser للـ notebooks صلاحيته على الداتابيز بتاعته بس.
4. **توليد داتا لسفننا الـ 500** (العيّنات مفيهاش رحلات لسفننا):
   - `AIS_generator.ipynb` ولّد **1,310,619 موقع**:
     - كل سفينة بتمشي في **بحر حقيقي** بين الموانئ، على مسار من شبكة `port_connections`.
     - حالتها متسقة مع جدول `vessels` (In Transit / At Port / Anchored / Completed).
     - أول نسخة كانت خطوط مستقيمة، و**49% من المواقع طلعت على اليابسة**. دلوقتي 0.96% بس، وكلهم جوه قنوات أضيق من الخريطة (السويس، بنما، الدردنيل…).
   - `EDI_generator.ipynb` ولّد **434 رسالة** (واحدة لكل شحنة)، فيها الـ 1,000 container بتوعنا، وتواريخها من نفس رحلات الـ AIS.
5. **Loader واحد بس بيكتب في Mongo** (`MongoDB_loader.ipynb`):
   - بيمسح ويعيد التحميل.
   - بعدها بيقرا من Mongo ويتأكد من كل حاجة: كل سجل ليه مصير (اتحمّل أو اترفض بسبب)، ومقارنة كاملة مع PostgreSQL.
   - تشغيله مرتين بيدّي نفس النتيجة بالظبط.

**النتيجة في MongoDB:**

| Collection | العدد |
|---|---:|
| `ais_positions` | 1,321,568 موقع (10,949 حقيقي + 1,310,619 synthetic) |
| `ais_vessels` | 10,534 سفينة (10,034 حقيقية + 500 بتوعنا) |
| `edi_messages` | 435 رسالة (العيّنة + 434 synthetic) |

---

## 3. القرارات المهمة (باختصار)

| القرار | ليه |
|---|---|
| هوية السفينة في PostgreSQL، وMongo بيشاور عليها بس | مرجع واحد، من غير تضارب |
| AIS/EDI **مش** هيدخلوا الـ RAG | دي داتا بتتسأل بـ tools/agents، مش نصوص بتتقرا |
| Loader واحد بيكتب، والـ generators بتطلّع ملفات | إعادة التشغيل دايماً بتطلّع نفس الحالة |
| أرقام IMO والـ containers بتوعنا متسلسلة: سيبناها | PostgreSQL هو المرجع؛ الـ check digit بيتفحص على الداتا الحقيقية بس |
| رسالة EDI مربوطة بآخر فاتورة للسفينة (`RFF+IV`، 376 رسالة) | هدفنا نقلّد الـ flow (تعليمات شحن ← رحلة ← فاتورة ← شريحة تعريفة) مش الأرقام الحقيقية؛ الربط متفحوص إنه لنفس السفينة |
| جدول `documents`: صف لكل ملف PDF، و`document_id` ثابت | كل chunk في Qdrant هيشاور على مصدره |

---

## 4. إيه اللي اتغير في PostgreSQL

| Migration | التغيير |
|---|---|
| 004–005 | عمود `vessels.mmsi` (500 رقم مختلفين) |
| 006 | **32 قاعدة CHECK** بتمنع أي داتا غلط (اتختبرت بـ 14 إدخال غلط، واترفضوا كلهم) + indexes على كل الـ FKs والخرايط |
| 007 | role `ports_readonly`: قراية بس، للـ agents |
| 008–009 | شرح (comment) على كل جدول وعمود، عشان الـ agents تفهم الداتا لوحدها |
| 010 | ملء جدول `documents`: 29 صف (2,163 chunk، 765 صفحة) |

وكمان:
- الـ container بقى على `127.0.0.1` بس. كان مفتوح على الشبكة كلها.
- اتجمعت الـ statistics اللي عمرها ما كانت اتجمعت.
- اتصلّح `SyntheticGenerator.ipynb` اللي كان بايظ من قبل.

**الحالة:** الـ audit كله أصفار، و0 errors (`db/audit/2026-09-27_after_010_report.txt`).

---

## 5. الـ notebooks والملفات المهمة

| Notebook | بيعمل إيه |
|---|---|
| `Notebooks/semi_structured/AIS_EDI_profiling` | يقرا الـ raw ويطلّع profiles |
| `Notebooks/semi_structured/AIS_generator` | مسارات السفن |
| `Notebooks/semi_structured/EDI_generator` | رسايل الـ EDI |
| `Notebooks/semi_structured/MongoDB_loader` | التحميل في Mongo والفحص |
| `Notebooks/rag/Documents_registry` | جدول `documents` |

الأوامر كلها في `db/README.md` و`db/mongo/README.md`.

---

## 6. فاضل عليك

1. ~~user القراية للـ agents~~ ✅ اتعمل (8/8)، و~~الـ Docker volume القديم~~ ✅ اتمسح.
2. تنضيف `Notebooks/_scratch` وتقارير التحميل القديمة.
3. `git commit`.

**فحص جاهزية الـ embeddings (2026-09-28):** الـ 2,163 chunk سليمين 100% (مفيش نص فاضي ولا مكرر ولا أطول من 2000 حرف)، وكلهم مربوطين بجدول `documents`.

## 7. الخطوة الجاية: الـ RAG

محتاج منك 3 قرارات:
1. **Embedding model:** local ولا API؟
2. **Qdrant في Docker:** أنصح بـ آه.
3. **Chunks:** نحمّل كام في الأول كتجربة قبل الكل؟
