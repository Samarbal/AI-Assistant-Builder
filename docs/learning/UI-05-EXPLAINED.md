# UI-05 — ربط ملفات المعرفة بالواجهة

Date: 2026-10-19
Status: implemented; controlled-response verification, pending developer review.

## ما الذي أصبح متاحًا؟

داخل المساعد، تبويب Knowledge يعرض الملفات وحالتها، ويرفع PDF/DOCX، ويطلب رابط تنزيل مؤقت، ويزيل ارتباط الملف بالـdraft بعد التأكيد. يدعم FR-003 وAC-004–007، وعزل حالة المالك ضمن AC-002، وربط المعرفة ضمن AC-003، وتجربة دون كود ضمن AC-018. لا توجد embeddings أو RAG أو Playground في هذه الخطوة.

## الملفات والمسؤوليات

- `frontend/src/knowledge/api.ts`: أنواع KnowledgeFile وDownloadLink، وحدود الحجم والعدد. validateFile يتحقق من الامتداد والاسم والحجم. knowledgeApi يرسل الطلبات الأربع إلى FastAPI باستخدام الجلسة الحالية، ويتحقق من owner/epoch قبل وبعد الرد. knowledgeError يعرض رسائل آمنة بدل تفاصيل الخادم.
- `frontend/src/knowledge/KnowledgeFiles.tsx`: KnowledgeFiles يعيد تركيب FileManager عند تغيير المساعد. FileManager يدير القائمة، اختيار الملف، العمليات والتأكيد. run يمنع تداخل عمليات الصفحة ويعيد قراءة القائمة بعد الرفع والإزالة، حتى عند فشل الرد. TemporaryDownload يحذف الرابط من العرض بعد انتهاء صلاحيته.
- `frontend/src/knowledge/knowledge.module.css`: تخطيط وبطاقات متجاوبة باستخدام ألوان ومكونات المشروع. الأيقونات محلية من Figma، بأبعادها الأصلية.
- `frontend/src/app/routes.tsx`: يربط `/assistants/:id/knowledge` بالشاشة الجديدة داخل RequireOwner الموجود.
- `frontend/tests/knowledge.test.tsx`: اختبارات المكونات والعميل وحدود الملفات والأخطاء وتغيير الحساب.
- `frontend/tests/browser/knowledge.spec.ts`: متصفح فعلي باستجابات HTTP مضبوطة، يرفع PDF/DOCX وينزّل bytes معروفة ويزيل ويستبدل الملف، ويتحقق من حد الخمسة وانتهاء الجلسة.

## مسار رفع ملف

اختيار ملف → validateFile → Upload file → knowledgeApi.upload → AuthStore.accessToken → multipart POST يحتوي حقل file فقط → Vite proxy → FastAPI الموجود → التحقق من المالك → حجز slot داخل معاملة RLS → استخراج النص والتخزين الخاص → تثبيت metadata → الرد → إعادة تحميل القائمة.

الواجهة لا ترسل owner_id أو مسار Storage. لا تضبط Content-Type يدويًا لـFormData؛ المتصفح يضيف multipart boundary. لا تكفي لاحقة PDF لإثبات صلاحية الملف؛ التحقق الحقيقي واستخراج النص في backend.

## لماذا نعيد القائمة حتى بعد الفشل؟

قد يُحجز slot قبل فشل الاستخراج أو Storage، أو ينجح الخادم بينما يضيع الرد. لذلك لا نعيد POST تلقائيًا. نقرأ القائمة أولًا. إن فشلت إعادة القراءة، تصبح الحالة غير مؤكدة وتُمنع العمليات حتى Refresh ناجح. الملف الفاشل ما زال محسوبًا ضمن الخمسة حتى إزالته.

مهلة الرفع في العميل 120 ثانية؛ بقية طلبات المعرفة 20 ثانية. إلغاء انتظار المتصفح لا يعني إلغاء معالجة الخادم. العمليات المتعثرة طويلًا تحتاج أداة recovery الموجودة للمطوّر، وليست مهمة واجهة جديدة.

## التنزيل والإزالة والأمان

التنزيل يرسل POST لإنشاء رابط، ثم يعرض رابط HTTPS مؤقتًا في ذاكرة الصفحة فقط. فتح الملف لا يرسل Authorization إلى Storage؛ صلاحية الوصول في الرابط نفسه. الرابط يفتح باستخدام noopener/noreferrer وتُزال إمكانية استخدامه محليًا بعد expires_in. عند تبديل الحساب تُزال شجرة المالك كاملة وتُلغى الطلبات؛ نتائج الحساب السابق لا تُقبل.

DELETE يرجع 204 بلا JSON. الإزالة تفصل الملف عن draft، ولا تمحو النسخة الفيزيائية فورًا ولا تُبطل الروابط السابقة قبل انتهاء صلاحيتها. تُزال الروابط من الواجهة عند بدء عملية جديدة أو طلب تأكيد الإزالة. إعادة ضبط الواجهة ليست بديلًا عن Auth وRLS في الخادم.

## التحقق والتشخيص

من frontend:

```powershell
npm.cmd test -- tests/knowledge.test.tsx
npm.cmd run test:browser -- tests/browser/knowledge.spec.ts
npm.cmd test
npm.cmd run test:browser
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

فشل اختبار التنزيل أولًا لأن mock كان page.route، بينما الرابط يفتح نافذة جديدة. الإصلاح في الاختبار هو browserContext.route كي يغطي أول طلب للنافذة الجديدة؛ لم يتغير عقد التطبيق. [توثيق Playwright](https://github.com/microsoft/playwright/blob/main/docs/src/api/class-page.md) يشرح هذا الفرق.

عند 409 راجع العدد والحالة، وعند 422 استخدم مستندًا مقروءًا غير مشفر وأزل الملف الفاشل، وعند 401 سجّل الدخول مجددًا. لا تنسخ التوكن أو الرابط الموقّع إلى تقارير الأخطاء. لا تُسمى حالة extracted جاهزية RAG؛ معناها نجاح قراءة النص فقط.

## أسئلة للفهم

1. لماذا نحسب الملف failed ضمن حد الخمسة؟
2. لماذا لا نقرأ JSON بعد DELETE الناجح؟
3. لماذا لا نعيد الرفع تلقائيًا بعد timeout؟
4. كيف يمنع owner/epoch وصول رد الحساب السابق إلى الحساب الجديد؟
5. لماذا قد يبقى رابط التنزيل صالحًا بعد إزالة الملف من draft؟

تمرين: حاكِ رفعًا يرجع 503 ثم قائمة تحتوي failed attachment. تحقق أن الرسالة واضحة وأن الملف ظاهر ومحسوب. حاكِ فشل GET التالي أيضًا وتأكد أن الرفع يُمنع حتى تنجح إعادة القراءة. لا تستخدم البيئة الحية للتمرين.

UI-06 والمراجعة الحية الشاملة ما زالا لاحقين. لم تُغيَّر بيانات Supabase أو backend أو الاعتماديات.

## نتائج التحقق

- Focused component/API tests: 14 passed.
- Focused browser tests: 3 passed، بعد تصحيح نطاق download mock.
- Full component/store regression: 51 passed، دون skips.
- Full Chromium regression: 17 passed، دون skips. حصل تعليق teardown داخل sandbox؛ الإعادة خارجها انتهت بنجاح وexit 0.
- TypeScript، lint وproduction build: PASS. ما زال تحذير bundle أكبر من 500 kB موجودًا (نحو 544 kB، أو 159 kB gzip).
- جميع طلبات الاختبار مضبوطة؛ لم تُنفذ تجربة حية أو تغيير في Supabase. يبقى التحقق اليدوي الحي والمراجعة الأشمل ضمن UI-06.
