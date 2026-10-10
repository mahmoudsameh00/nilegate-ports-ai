<div dir="rtl">

# ملخص مرحلة الـ RAG retrieval (اتقفلت 2026-10-08)

ملخص بسيط لكل اللي اتعمل في مرحلة الـ RAG: عملنا إيه، واستخدمنا إيه، وليه، والملفات فين. التفاصيل الكاملة في
`docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md` و`docs/decisions.md` (من ADR-037 لحد ADR-044).

---

## 1. الفكرة في جملة

كان عندنا 2,163 chunk من 29 ملف PDF، بس محدش يقدر يدوّر فيهم. دلوقتي فيه **أداة واحدة** اسمها
`search_documents` بتاخد السؤال ورقم الموظف، وترجّع أنسب 8 chunks للسؤال، **وبتخفي أي chunk الموظف ده مش مسموحله يشوفه**،
ومع كل chunk مصدره (الملف والصفحة). دي الأداة اللي الـ agents هيستخدموها بعد كده.

**السؤال بيمشي كده:**
1. الأداة بتاخد السؤال ورقم الموظف.
2. تسأل PostgreSQL: الموظف ده role إيه وقسم إيه؟ (بـ user صلاحيته قراءة بس)
3. Gemini يحوّل السؤال لـ vector، ولو السؤال اتسأل قبل كده بيتجاب من الـ cache.
4. Qdrant يدوّر في الـ 2,163 chunk، وفلتر الصلاحيات شغال جوه البحث نفسه.
5. أحسن 24 مرشح بيروحوا لـ Jina reranker يرتّبهم من جديد.
6. بيرجع أحسن 8، ومع كل واحد مصدره.

---

## 2. المراحل بالترتيب: عملنا إيه وليه

### المرحلة 0: نتأكد إن المزوّدين شغالين (2026-10-01)
- **السكربت:** `Provider_smoke_test.py` جرّب 3 مزوّدين للـ embeddings (Jina وVoyage وGemini) ومعاهم Jina reranker، والأربعة نجحوا.
- **ليه؟** قبل ما نبني أي حاجة، نتأكد إن الـ keys شغالة والـ free tier متاح فعلاً.

### المرحلة 1: أسئلة الامتحان قبل الامتحان (2026-10-02)
- **السكربت:** `Golden_set.py` بيطلّع `golden_set.jsonl`، وفيه:
  - **40 سؤال إنجليزي + 24 نسخة منهم بالعامية المصرية**.
  - 9 أسئلة بأكواد وأرقام (زي `MSC-MEPC.3/Circ.4/Rev.1` وأرقام MISLE).
  - 8 حالات صلاحيات (RBAC).
- **اتقفل بـ hash**، فمحدش يقدر يعدّله من غير ما يبان.
- **ليه قبل أي موديل؟** لو كتبنا الأسئلة بعد ما نجرب الموديلات، هنكتب من غير ما نقصد أسئلة الموديل المفضّل بيعرف يجاوبها.
- **بعدها:** `Golden_facts.py` طلّع 80 "حقيقة" مطلوبة للـ 40 سؤال. كده التقييم بقى مش بس "الـ chunk الصح طلع؟" لكن كمان
  "المعلومة المطلوبة موجودة في اللي طلع؟" (ADR-040).

### المرحلة 2: الـ Bake-off، مين أحسن موديل embeddings؟ (من 2026-10-02 لـ 10-08)
- **السكربت:** `Embedding_bakeoff.py`. كل موديل حوّل الـ 2,163 chunk لـ vectors، وبعدين جاوب على الأسئلة الذهبية.
- **النتيجة (D1 score):**

  | الموديل | النتيجة |
  |---|---:|
  | Gemini `gemini-embedding-2` | **0.912** |
  | Voyage `voyage-4` | 0.804 |
  | Jina `jina-embeddings-v5-text-small` | 0.733 |

  وفي العربي بالذات Gemini كان أقوى بكتير (hit@10 كان 0.875 مقابل 0.708).
- **القرار:** Gemini (ADR-037)، مع إنه ماكانش الاختيار المبدئي، لإننا كنا متوقعين Jina.
- **اكتشاف مهم في الطريق (ADR-041):** تقارير USCG كانت بتحط العنوان جوه النص نفسه، فالمقارنة كانت ظالمة. عملنا قاعدة
  واحدة للكل:
  - الـ `title` = مكان الـ chunk (الملف، والقسم، ورقم البند).
  - الـ `text` = المحتوى بس.
  - اللي بيتحوّل لـ vector = الـ title وبعده سطر جديد وبعده الـ text.
- **مشكلة:** الـ free tier بتاع Gemini بيسمح بحوالي 1,000 لـ 1,450 نص في اليوم، فالـ bake-off اتعمل على كذا يوم.
  **الحل:** كل vector بيتحفظ (files-first cache)، والتشغيل بيكمّل من مكان ما وقف.

### المرحلة 3: الـ Qdrant في Docker (2026-10-02)
- **الأدوات:** `db/qdrant/create_container.ps1` و`probe_qdrant.py`.
- **الإعداد:** container اسمه `ports-qdrant` (نسخة 1.19.1 متثبتة)، شغال على جهازك بس (على 127.0.0.1)، وكل طلب محتاج API key.
- **الـ probe اختبر:** إن Qdrant نفسه بيقدر يعمل BM25 (فمحتجناش مكتبة زيادة)، وإن فلتر الصلاحيات بيشتغل جوه البحث.

### المرحلة 4: نحوّل الـ corpus كله لـ vectors (من 2026-10-05 لـ 10-08)
- **السكربت:** `Embeddings.py` بيطلّع `dense_composed.parquet` في `Data/embeddings/gemini-embedding-2/` (2,163 × 3,072 رقم).
- **ملف `manifest.json`** (وده الوحيد اللي في git): فيه hash كل نص وhash الملف، فأي حد يقدر يتأكد إن الـ vectors بتاعته
  مطابقة.

### المرحلة 5: نحمّل Qdrant (2026-10-08)
- **السكربت:** `Qdrant_loader.py`، وهو **الوحيد اللي بيكتب في Qdrant**.
- **التحميل:** جرّبناه الأول على ملف واحد (LPI Methodology، فيه 94 chunk)، وبعدين الـ 29 ملف.
- **كل point فيها:**
  - الـ `dense` (الـ vector بتاع Gemini).
  - الـ `bm25` (يبنيه Qdrant).
  - الـ payload = الـ 16 عمود + `document_id`.
- **رقم الـ point ثابت** = قيمة UUID5 من `document_id` و`chunk_id`، فلو شغّلت التحميل تاني مفيش أي تكرار (ADR-039).
- **بعد التحميل** قرينا كل حاجة من Qdrant وقارنّاها بالملفات: كل الـ payloads مطابقة، والتحميل التاني ماغيّرش حاجة.

### المرحلة 6: أداة البحث نفسها (2026-10-08)
- **مكانها:** `pipelines/lib/retrieval.py` (الدالة `search_documents`)، وبيتأكد منها `Retrieval.py`.
- **اللي فيها:**
  - فلتر RBAC (من ADR-006) جوه كل جزء من البحث.
  - فلاتر metadata: نوع الملف، والسنة، ونوع الوحدة (`unit_kind`).
  - query cache.
  - سياسة rate limit بتفشل بسرعة بدل ما تستنى.
- **اختبار الصلاحيات:** 11 موظف × 4 أسئلة level 3 × (dense وhybrid) = 88 بحث، والـ CEO بس اللي شاف level 3.
- **سؤال السرعة (HNSW ولا لأ؟):**
  - الـ benchmark (`Search_index_benchmark.py`) قارن exact بـ IVF وHNSW. مع 2,163 نقطة بس، البحث الكامل (exact) دقيق 100%
    وسريع، فخلّيناه.
  - **95% من وقت البحث كان في تحويل السؤال لـ vector** (حوالي 500 ms)، مش في Qdrant، وعشان كده عملنا الـ cache.
- **الـ Redis ولا لأ؟** قسناه: الـ cache في الذاكرة بياخد 0.2 ميكروثانية، وRedis بياخد 0.57 ms. فـ Redis اتأجل لحد ما يبقى
  فيه أكتر من worker (في مرحلة الـ API).

### المرحلة 7: التقييم، نختار الإعدادات بالأرقام (2026-10-08)
- **السكربت:** `Evaluation.py` بيطلّع `results_2026-10-08.json`، وده الـ **baseline** اللي الـ agents ممنوع ينزلوا عنه.
- **التقييم على 3 مستويات (ADR-040):** هل الحاجة الصح طلعت؟ هل اترتبت كويس؟ هل الـ context كفاية؟
- **النتيجة (ADR-038):**

  | الإعداد | النتيجة (balanced) | القرار |
  |---|---:|---|
  | الـ dense بس | 0.812 | — |
  | **الـ dense ومعاه Jina rerank** | **0.850** | ✅ الإعداد الافتراضي |
  | الـ hybrid (BM25) | أقل | ❌ اترفض |
  | حد أقصى 2 chunks لكل ملف | 0.247− | ❌ بيرمي معلومات |
  | شيل المتكرر | 0.007− | ❌ اترفض |

- **ثمن الـ reranker:** حوالي 0.6 لـ 1.5 ثانية لكل سؤال. ولو Jina وقع أو عمل rate limit، بنرجع لترتيب الـ dense بعد 5 ثواني.

### المرحلة 8: مستند بيترفع وقت المحادثة (2026-10-08)
- **السؤال:** موظف رفع PDF أو DOCX وعايز يسأل عليه. نتعامل معاه إزاي من غير ما يبوّظ الـ corpus أو يسرّب حاجة؟ (من ADR-042
  لحد ADR-044)
- **قالب واحد للشركة:** اسمه "NileGate Document v1" وموجود في `docs/templates/`. أي ملف برّه القالب بيترفض برسالة واضحة.
- **فحص الأمان (screening):**
  - يدوّر على نص مخفي (أبيض على أبيض، أو حجمه صفر).
  - يدوّر على محاولات prompt injection بالإنجليزي والفصحى والعامية المصرية.
  - القراءة بتحصل في process منفصلة عشان لو الملف خبيث.
- **المستند بيعيش في الذاكرة بس** لمدة المحادثة (8 ساعات)، وصاحبه الوحيد اللي يقدر يبحث فيه.
- **موديل محلي:** الموديل `BAAI/bge-m3` بيشتغل بـ ONNX Runtime على جهازك، فنص المستند **مابيطلعش برّه الجهاز**.
- **نتيجة البحث بقت قايمتين:** قايمة `results` للـ corpus (ومش متأثرة خالص)، وقايمة `session_results` للمستند المرفوع
  (ومتعلّم عليها إنها `untrusted_upload`).
- **الترقية (promotion):** مدير القسم بس يقدر يطلب إن مستنده يدخل الـ corpus الدائم، وإنت (المالك) بتراجع وتوافق.
- **الأرقام:**
  - كل الـ 52 fixture (ملفات سليمة وهجمات) طلعوا زي المتوقع، ومفيش ولا false positive على الـ corpus.
  - الـ baseline ماتغيرش (0.812 و0.8495)، والعزل بين المستخدمين 15 من 15.
  - موديل bge-m3 جاب hit@3 للإنجليزي 1.000 وللعربي 0.900 بعد الـ floor 0.45.
  - رفع ملف من 3 صفحات بياخد حوالي 4 ثواني.
- **موديلك المقترح** (`llama2-embedding-600m-8k`) اتقاس وماعداش الحد (العربي جاب 0.167)، فاخترنا bge-m3 بالأرقام.

### المرحلة 9: الإغلاق (2026-10-08)
- **الـ Migration 011:** عمود `documents.ingested_at` اتملا للـ 29 ملف، والـ audit سليم.
- **نقل الـ bake-off cache:** كان في `_scratch` و3 سكربتات معتمدة عليه، فاتنقل لـ `Data/embeddings/bakeoff/`.
- **الموديلات المرفوضة:** اتمسحت (6.4 GB)، والسكربت `Upload_eval` بقى بيقرا أرقامهم المسجلة.
- **قاعدة اختيار الـ precision:** بقى ليها هامش 20% عشان الـ noise مايقررش.
- **الـ docs:** اتحدّثت، والخطة اتأرشفت.

---

## 3. استخدمنا إيه وليه

| الحاجة | بتعمل إيه | ليه هي |
|---|---|---|
| موديل **Gemini** `gemini-embedding-2` عن طريق API | يحوّل النص لـ vector (3,072 رقم) | كسب الـ bake-off، خصوصاً في العربي، ومجاني |
| موديل **Jina** `jina-reranker-v3.5` عن طريق API | يعيد ترتيب أحسن 24 مرشح | رفع النتيجة من 0.812 لـ 0.850 |
| قاعدة **Qdrant 1.19.1** في Docker | قاعدة الـ vectors + فلتر الصلاحيات جوه البحث | الـ dense والـ sparse في collection واحدة، والفلتر جوه البحث، وخفيف (ADR-001) |
| مكتبة **qdrant-client** | الكلام مع Qdrant من Python | العميل الرسمي |
| مكتبة **httpx** | كل طلبات الـ APIs (Gemini وJina وVoyage) | client واحد للـ retries والـ rate limits، ومن غير قيود vendor SDK |
| قاعدة **PostgreSQL** بـ user قراءة بس | منين نعرف role وقسم الموظف | الصلاحيات بتيجي من الداتابيز، مش من نص السؤال (ADR-034) |
| الموديل **bge-m3** مع ONNX Runtime وtokenizers | embeddings محلية للمستندات المرفوعة | نص المستند مابيطلعش برّه الجهاز، ومن غير quota |
| مكتبة **defusedxml** | قراءة DOCX بأمان | ملفات DOCX اللي المستخدمين بيرفعوها ممكن تكون خبيثة (هجمات XML) |
| مكتبة **PyMuPDF** (كانت موجودة) | قراءة PDF المرفوع | نفس المكتبة اللي في الـ ingestion |

**اللي جربناه ورفضناه بالأرقام:**
- موديلات Jina وVoyage للـ embeddings.
- الـ hybrid BM25 (فاضل متخزن ومتاح للأكواد بعدين).
- الـ context shaping.
- الـ HNSW والـ IVF (مفيش مكسب مع الحجم ده).
- الـ Redis (اتأجل).
- موديلات llama2-600m وe5-base كموديلات محلية.
- الـ DirectML (اتأجل).
- الـ pgvector (من الأول، ADR-001).

---

## 4. الملفات: كل حاجة فين

### الـ library في `pipelines/lib/` (الكود اللي الـ agents هيستخدمه)
| الملف | بيعمل إيه |
|---|---|
| `common.py` | يلاقي جذر المشروع، ويقرا `.env`، ويخفي الـ keys من رسايل الخطأ |
| `chunks.py` | قاعدة الـ title والـ text (ADR-041)، والدالة `compose()`، والتحقق من الـ 16 عمود |
| `embeddings.py` | الكلام مع مزوّدي الـ embeddings، والـ rate limit، والـ retries، والـ cache اللي بيكمّل من مكان ما وقف |
| `qdrant_store.py` | مواصفات الـ collection، ورقم الـ point الثابت، والتحميل الآمن، والتحقق |
| `retrieval.py` | الدالة **`search_documents`**: الصلاحيات، والفلاتر، والـ cache، والـ reranker، والـ session lane |
| `evaluation.py` | مقاييس التقييم (hit وMRR وfact recall وnDCG وsufficiency وغيرهم) |
| `upload_reader.py` | قراءة الـ PDF أو الـ DOCX المرفوع في process منفصلة، وكشف النص المخفي |
| `screening.py` | كشف الـ prompt injection (إنجليزي وفصحى وعامية) |
| `uploads.py` | التحقق من قالب NileGate Document v1، وتقسيم المستند لـ chunks |
| `local_embeddings.py` | تشغيل bge-m3 محلياً بـ ONNX Runtime |
| `session_store.py` | مستندات المحادثة في الذاكرة لكل موظف، ومدة 8 ساعات، وطلب الترقية |

### السكربتات في `pipelines/scripts/retrieval/`
| السكربت | بيعمل إيه | المرحلة |
|---|---|---|
| `Provider_smoke_test.py` | يتأكد إن الـ keys شغالة | 0 |
| `Golden_set.py` | الأسئلة الذهبية (مقفولة بـ hash) | 1 |
| `Golden_facts.py` | الحقايق المطلوبة لكل سؤال | 1 و2 |
| `Embedding_bakeoff.py` | مقارنة موديلات الـ embeddings | 2 |
| `Embeddings.py` | الـ vectors بتاعة الـ corpus كله | 4 |
| `Qdrant_loader.py` | تحميل Qdrant (الكاتب الوحيد) | 5 |
| `Search_index_benchmark.py` | الـ exact مقابل IVF وHNSW | 6 |
| `Retrieval.py` | اختبار `search_documents` (صلاحيات، وفلاتر، وcache، وسرعة) | 6 |
| `Evaluation.py` | اختيار الإعدادات بالأرقام | 7 |
| `Lib_selftest.py` | اختبار الـ library كلها من غير API calls | من 2 لـ 8 |
| `Upload_fixtures.py` | يولّد 52 ملف اختبار (سليمة وهجمات) | 8 |
| `Upload_validation.py` | يتأكد إن كل ملف اختبار اتعامل صح | 8 |
| `Upload_eval.py` | يقيس الموديل المحلي والـ floor والعزل والسرعة | 8 |
| `Upload_promotion.py` | مراجعة وموافقة وتحميل مستند مرقّى، وفيه `--selftest` | 8 |

### أدوات وإعدادات
- الفولدر `db/qdrant/`: إنشاء الـ container والـ probe والـ README.
- السكربت `tools/export_onnx.py`: تصدير bge-m3 لـ ONNX مرة واحدة، في بيئة مؤقتة.
- الفولدر `docs/templates/`: قالب NileGate Document v1، ومعاه مثال DOCX.
- الـ migration `db/migrations/011_documents_ingested_at.sql`.

### الداتا اللي اتولّدت
| الملف | فيه إيه | في git؟ |
|---|---|---|
| `golden_set.jsonl` و`golden_facts.jsonl` في `Data/processed/rag/eval/` | الأسئلة والحقايق | ✅ |
| `bakeoff_results.json` في نفس الفولدر | نتايج الـ bake-off | ✅ |
| `results_2026-10-08.json` في نفس الفولدر | الـ baseline | ✅ |
| الفولدر `Data/processed/rag/eval/uploads/` | الـ fixtures وتقارير الـ uploads | ✅ |
| `manifest.json` في `Data/embeddings/gemini-embedding-2/` | الـ hashes بتاعة الـ vectors | ✅ |
| `dense_composed.parquet` والـ caches في نفس الفولدر | الـ vectors نفسها | ❌ كبيرة، وبتتولد تاني |
| الفولدر `Data/embeddings/bakeoff/` | الـ vectors بتاعة كل المرشحين | ❌ |
| الفولدر `models/onnx/bge-m3/` | الموديل المحلي (3.5 GB) | ❌ |
| الـ volume بتاع Docker `ports-qdrant-data` | الـ collection `nilegate_docs` | في Docker |

### الـ docs اللي اتحدّثت
`ARCHITECTURE.md` و`docs/ROADMAP.md` و`docs/DATA_MAP.md` و`docs/RETRIEVAL_FLOW.md` و`docs/decisions.md` (من ADR-037 لحد
ADR-044، ومعاهم الـ amendments) و`pipelines/README.md` و`db/README.md` وقواعد المشروع.

---

## 5. القرارات المهمة (باختصار)

| القرار | المحتوى |
|---|---|
| ADR-037 | موديل Gemini `gemini-embedding-2` (3,072 بُعد) على الـ title والـ text مع بعض. وماينفعش داتا حقيقية غير عامة تروح للـ free tier |
| ADR-038 | الإعداد الافتراضي: exact dense ومعاه Jina rerank. مفيش hybrid ومفيش shaping. والـ bm25 متخزن بس مش مستخدم |
| ADR-039 | الـ library مشتركة في `pipelines/lib/`، ورقم الـ point = قيمة UUID5 من `document_id` و`chunk_id` |
| ADR-040 | التقييم على 3 مستويات (retrieval وranking وcontext) |
| ADR-041 | قاعدة title وtext واحدة للـ corpus كله |
| ADR-042 | المستندات المرفوعة: قالب واحد، وvalidator، وscreening على طبقات |
| ADR-043 | المستندات المرفوعة في الذاكرة بس، وموديل محلي، وقايمتين نتايج منفصلين |
| ADR-044 | الترقية للـ corpus: طلب من مدير القسم، بعده مراجعة offline، بعدها تسجيل زي باقي الملفات |

---

## 6. أرقام تفتكرها

| البند | الرقم |
|---|---|
| الـ corpus | 2,163 chunk من 29 ملف و7 مصادر، منهم 5 chunks في level 3 (للـ CEO بس) |
| أحسن نتيجة retrieval | **0.850** balanced (الـ dense ومعاه rerank)، وتسريب الصلاحيات **صفر** |
| سرعة البحث | الـ Qdrant من 8 لـ 22 ms، وتحويل السؤال لـ vector حوالي 500 ms (أو صفر لو في الـ cache)، والـ rerank من 0.6 لـ 1.5 ثانية |
| المستندات المرفوعة | حوالي 4 ثواني لملف 3 صفحات، والبحث فيها حوالي 60 ms |
| الـ free tier بتاع Gemini | حوالي 1,000 لـ 1,450 نص في اليوم |

---

## 7. عشان تشغّل أي حاجة تاني

- **الـ Docker:** لازم `ports-postgres` و`ports-qdrant` يكونوا شغالين، بالأمر `docker start ports-postgres ports-qdrant`.
- **ملف `.env`:** محتاج `GEMINI_API_KEY` و`JINA_API_KEY` و`QDRANT_API_KEY` ومتغيرات `PG_RO_*` (والـ Voyage للـ bake-off بس).
- **التشغيل:** أي سكربت بيتشغل بـ `uv run python tools/run.py pipelines/scripts/retrieval/<اسم>.py`، والسطر اللي بيبدأ بـ ✅
  معناه إن المرحلة نجحت.
- **الـ Dashboard بتاع Qdrant:** على `http://127.0.0.1:6333/dashboard`، وبيطلب `QDRANT_API_KEY`.

## 8. حدود معروفة
- الـ reranker بيزوّد حوالي ثانية لكل سؤال، وJina مابيعلنش حدوده (وعندنا fallback).
- كل سؤال بيفتح اتصال PostgreSQL جديد (حوالي 18 ms)، والـ pool جاي في مرحلة الـ agents.
- لو حد عمل clone جديد، هيحتاج يعيد الـ embeddings (حوالي يومين على الـ free tier) أو ينسخ `Data/embeddings/`.
- الـ BM25 متخزن ومتاح، ومرشّح لأسئلة الأكواد في مرحلة الـ agents.

</div>
