# Phase 3 — Task 2: Deterministic Chunking

التاريخ: 2026-10-20. اكتملت هذه المهمة محليًا؛ Phase 3 كاملة لم تنتهِ.

## الفكرة

Phase 2 تحفظ النص المستخرج. أضفنا مكوّنًا يقسم هذا النص إلى مقاطع تصل إلى
600 tokens مع تداخل يقارب 100 tokens. التداخل يحافظ على بعض السياق بين المقاطع.
لم نضف embeddings أو retrieval أو endpoint جديدًا.

## الملفات والعلاقات

- `backend/src/assistant_builder/chunking.py`: واجهات `Chunker` و`Tokenizer`،
  ونماذج `SourceText` و`Chunk` و`ChunkingConfig`، والتنفيذ `DeterministicChunker`.
  المدخلات نصوص محفوظة مع owner/assistant/file IDs وإصدار الاستخراج؛ المخرجات tuple
  ثابتة من المقاطع أو خطأ واضح. لا يعرف المكوّن SQLAlchemy أو مفاتيح الخدمات.
- `backend/tests/test_chunking.py`: اختبارات الحدود، العربية والإنجليزية وUnicode،
  التداخل والثبات والهوية والإصدارات والميزانيات ورفض offsets غير الصحيحة.
- `backend/pyproject.toml` و`backend/uv.lock`: إضافة tiktoken وقفل نسخته 0.14.0
  وتبعياته؛ لم نضف framework للـRAG.
- `docs/ai-sdlc/contracts/PHASE-0-CONTRACTS.md`: مواصفات Task 2 وحدودها.
- `docs/ai-sdlc/plans/PLAN-001.md`: حالة التنفيذ والاختبارات والبوابة التالية.

في التكامل المستقبلي: service يتحقق من المالك، يقرأ `knowledge_file_text` عبر
repository وRLS، ثم يحول الصفوف إلى `SourceText` ويستدعي `chunk`. هذه المهمة
نفذت الجزء الخالص الأخير فقط؛ لم تربطه بطلب HTTP أو قاعدة بيانات.

## كيف يعمل؟

1. يتحقق من خمسة ملفات كحد أقصى، وعدم تكرارها، ومن اشتراكها في المالك والمساعد.
2. يرتبها حسب file UUID ليبقى الناتج ثابتًا حتى لو اختلف ترتيب استعلام DB.
3. يتحقق من النص وإصدار الاستخراج، ثم يعد tokens باستخدام tiktoken.
4. يرفض corpus يتجاوز 100,000 source tokens؛ الحد يشمل جميع الملفات.
5. ينشئ النوافذ باستخدام offsets، ويعيد عد tokens لكل slice فعلي.
6. يحفظ النص كما هو مع offset البداية والنهاية والـhash والإصدارات.
7. يعيد النتيجة بعد اكتمالها فقط. تجاوز 200 chunks يرفض العملية دون قائمة جزئية.

الـoffset هنا فهرس Unicode في Python والنهاية غير مشمولة. ليس رقم صفحة أو
byte offset أو index في JavaScript. قد تحتوي emoji على عدة tokens؛ لا يجوز
فك ترميز مجموعة tokens عشوائيًا واستبدال الجزء المكسور بـ replacement character.
لذلك نستخدم offsets المكتبة ونأخذ slice من النص الأصلي، ثم نعيد عدّه.
لا نغير المسافات أو التطبيع؛ وقد تنفصل جملة أو grapheme cluster عند الحد.

الـUUIDv5 حتمي: يتغير عند تغير الملف أو النص أو extraction version أو tokenizer
أو إعدادات النافذة. هذا يساعد على تتبع التغييرات، لكنه ليس بديلًا عن authorization.

## لماذا tiktoken؟

هي مكتبة maintained بدل كتابة tokenizer خاص أو اعتبار كل كلمة token.
`cl100k_base` اختيار مؤقت للمكوّن وليس اختيار embedding provider. قبل الفهرسة
نراجع tokenizer الفعلي للنموذج ونختبر الاستخدام العربي والإنجليزي. إذا تغيرت
المساحة أو tokenizer نغيّر fingerprint ونعيد الفهرسة بطريقة مضبوطة.

أول تهيئة قد تحمل قاموسًا عامًا من الإنترنت؛ تم تجهيز cache للاختبارات.
لا ترسل المكتبة نصوص المستخدم إلى provider. تجهيز cache جزء مطلوب من النشر
لاحقًا. القيود الحالية تحد حجم العمل؛ ليست sandbox لوقت المعالج أو الذاكرة.

## التحقق

من `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_chunking.py -q -p no:cacheprovider
$env:PHASE1_LOCAL_PG_TESTS='0'
.\.venv\Scripts\python.exe -m pytest -q -r s -p no:cacheprovider
uv lock --check --offline
```

- Focused: **34 passed**.
- Backend regression: **179 passed, 27 skipped, 3 warnings**.
- الاختبارات المتخطاة هي PostgreSQL المحلية؛ ليست دليلًا على RLS حي.
- التحذيرات الموجودة تخص Starlette/httpx وAlembic path separator.
- lock check وscoped diff check نجحا.
- أول تشغيل واجه مشكلة أسماء اختبارات طويلة على Windows؛ استبدلنا الأسماء
  المولدة من النص الطويل بأسماء حالات قصيرة، ثم نجح التشغيل.

هذه الاختبارات تدعم أساس AC-008/017، ولا تعني تنفيذ Playground أو جودة RAG.
لا مفاتيح أو ملفات حقيقية أو تغييرات Supabase أو نشر أو commit/push.

## أسئلة للفهم

1. لماذا نستخدم token count بدل عدد الكلمات؟
2. ما الفرق بين source tokens وtokens التي يعاد تكرارها بسبب overlap؟
3. لماذا نحتفظ بالنص الأصلي وoffsets بدل decode عشوائي للـtokens؟
4. لماذا يتغير chunk ID إذا تغير extraction version مع بقاء النص نفسه؟
5. لماذا لا تكفي مطابقة owner_id داخل chunker لإثبات صلاحية الوصول؟

تمرين: غيّر overlap إلى صفر داخل اختبار فقط، وتحقق أن جمع نصوص المقاطع يعيد
النص الأصلي تمامًا. ثم جرّب نصًا عربيًا مع emoji وحدد الفرق بين offsets وtokens.

المتبقي قبل Task 3: اعتماد embedding model/dimension والتحقق من tokenizer،
ثم مراجعة migration وRLS وrecovery compatibility. لا تبدأ المهمة التالية تلقائيًا.
