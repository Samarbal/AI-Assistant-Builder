# UI-UX-SPRINT-001 — UI-02 learning review

تاريخ المراجعة: 2026-10-17. يحتوي هذا الملف على مراجعة UI-02 التاريخية ثم
مراجعة UI-03 أدناه. UI-02 تمت مراجعتها، وUI-03 جاهزة للمراجعة قبل UI-04.

## ماذا بنينا ولماذا؟

أنشأنا واجهة مستقلة داخل `frontend/` باستخدام React وTypeScript وVite.
الهدف تجهيز الهيكل المرئي والتنقل والمكونات المشتركة قبل إضافة تسجيل الدخول
وربط بيانات المساعدين. Phase 2 تبقى مكتملة وPhase 3 مؤجلة وليست ملغاة.

التصميم يعتمد على Figma: sidebar بعرض 240px، header بارتفاع 72px، لون بنفسجي،
خط Inter محلي، بطاقات وحدود خفيفة، وقائمة سفلية للموبايل. أزلنا بيانات الشركة
الوهمية والإحصاءات غير المدعومة، وأضفنا تنبيه UI preview حتى لا تبدو الواجهة
وكأنها قرأت حسابًا حقيقيًا. لا يوجد حفظ أو تحميل ملفات في هذه الخطوة.

هذا العمل يدعم NFR-001/002 وأساس التنقل لـAC-018. لا يثبت وحده AC-001–007؛
هذه تحتاج ربطًا واختبارات حقيقية في مهام الواجهة التالية. صلاحيات backend وRLS
لم تتغير ولم نجرِ اتصالًا بقاعدة البيانات.

## الملفات والطبقات

كل المسارات التالية نسبية لجذر المشروع:

| الملف | المسؤولية والعلاقة بالملفات الأخرى |
| --- | --- |
| `frontend/index.html` | نقطة دخول المتصفح والعنوان وviewport؛ يحمل `src/main.tsx` |
| `frontend/src/main.tsx` | يركّب React داخل root، ثم BrowserRouter وAppRoutes، ويحمّل الخط والأنماط |
| `frontend/src/app/routes.tsx` | `AppRoutes` يربط عناوين الصفحات بمكوناتها داخل Shell، مع مسارات متداخلة للمساعد |
| `frontend/src/app/Shell.tsx` | `Shell` يعرض sidebar/header/main، و`Navigation` يعيد استخدام الروابط؛ Outlet يعرض الصفحة الحالية |
| `frontend/src/app/shell.module.css` | تخطيط desktop/mobile وdialog؛ CSS Modules تمنع تعارض أسماء الأنماط |
| `frontend/src/pages/Pages.tsx` | `Overview` يعرض معاينة الحالة الفارغة، `Placeholder` يشرح العمل المؤجل، `AssistantLayout` يعرض التنقل بين Configuration وKnowledge |
| `frontend/src/pages/pages.module.css` | تخطيط العناوين والبطاقات والتبويبات المتجاوبة |
| `frontend/src/components/ui.tsx` | Button/ButtonLink وTextField وBadge وCard وAlert وEmptyState وLoadingState؛ تأخذ props وتنتج واجهة دون اتصال بيانات |
| `frontend/src/components/ui.module.css` | أشكال المكونات وحالات disabled/error/loading |
| `frontend/src/components/Icon.tsx` | خريطة SVG محلية؛ الأيقونات زخرفية واسم الزر يأتي من النص |
| `frontend/src/styles/tokens.css` | الألوان والمسافات والزوايا المشتركة المستخرجة من التصميم |
| `frontend/src/styles/global.css` | الخط، reset محدود، focus-visible، وتقليل الحركة |
| `frontend/src/assets/icons/` | 14 أيقونة Figma محلية؛ مصدرها وأبعادها موثقان في `src/assets/README.md` |
| `frontend/package.json`, `package-lock.json` | أوامر التشغيل واعتماديات مثبتة؛ `npm ci` يعيد التثبيت من lockfile |
| `frontend/vite.config.ts` | React plugin وخادم تطوير loopback؛ لا proxy أو اتصال backend |
| `frontend/tsconfig*.json` | TypeScript strict للتطبيق والاختبارات والإعدادات |
| `frontend/.oxlintrc.json` | قواعد Oxlint التي جاء بها scaffold مع hooks rules |
| `frontend/vitest.config.ts`, `tests/setup.ts` | بيئة jsdom، تنظيف DOM بين الاختبارات وتعويض APIs المتصفح غير المتاحة |
| `frontend/tests/foundation.test.tsx` | اختبارات المسارات والمكونات وحالاتها |
| `frontend/playwright.config.ts`, `tests/browser/shell.spec.ts` | خادم مؤقت واختبارات Chromium للموبايل والتنقل والموارد المحلية |
| `frontend/.gitignore` | يستبعد dependencies/build/reports وملفات البيئة |

## تتبع عملية واحدة

عند الضغط على Create assistant، يمر التنفيذ عبر `ButtonLink` ثم React Router،
فيتغير URL إلى `/assistants/new`. يختار `AppRoutes` مكون `Placeholder`، ويظهر
داخل `Shell` عبر `Outlet`. يبقى sidebar ثابتًا ويتغير المحتوى. ينقل effect في
Shell التركيز إلى main ويحدث عنوان المتصفح. **لا يحدث POST ولا تُنشأ بيانات**.

في مسار `/assistants/example/configuration`، الرابط النسبي Knowledge يحافظ على
جزء المساعد ويذهب إلى `/assistants/example/knowledge`. كلمة example مجرد قيمة
لتجربة التخطيط؛ لا تعني وجود سجل. المسارات غير المعروفة تعرض Page not found.

بعد UI-03/04 فقط سيكون هناك تدفق بيانات عبر Auth ثم FastAPI والخدمات والمستودعات
وقاعدة البيانات. لم ننشئ تدفقًا شكليًا يوهم بأن هذه الطبقات متصلة الآن.

## القرارات المهمة

- SPA بسيطة لأن هذه لوحة إدارة، ولا توجد حاجة حالية إلى SSR أو backend ثانٍ.
- React Router في Declarative mode: Routes/Route/Outlet، دون loaders أو شبكة مخفية.
- CSS variables للمظهر وCSS Modules للمكونات بدل إضافة مكتبة UI أو Tailwind.
- Inter وأيقونات Figma محلية لتجنب الاعتماد على روابط مؤقتة أو مزود خطوط خارجي.
- Button يستخدم disabled أثناء busy لمنع تكرار الضغط؛ ButtonLink يبقى رابطًا
  للتنقل، فلا نخلط الضغط لتنفيذ عملية مع الانتقال لصفحة.
- TextField يربط label وhint/error باستخدام useId وaria-describedby؛ التحقق
  من النماذج الفعلية سيأتي مع workflows، وليس في صفحات المعاينة.
- dialog الأصلي يمنع التفاعل مع الخلفية، مع تدوير صريح لـTab/Shift+Tab بين أول
  وآخر عنصر. Escape يعيد التركيز للمشغّل، والتنقل يعيده للمحتوى. التحول إلى
  desktop يغلق قائمة الموبايل حتى لا تبقى طبقة فوق sidebar.

## الاختبارات والتصحيح

من مجلد `frontend`:

```powershell
npm run typecheck
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:browser
```

`foundation.test.tsx` يغطي 8 مسارات، التنقل لإنشاء مساعد دون حفظ، التنقل بين
أقسام المساعد، منع busy/disabled actions، ربط الحقول بالأخطاء، وإعلان حالات
loading/error. اختبارات المتصفح تغطي 320/390/768/1440px، الصور المحلية، غياب
الطلبات الخارجية، deep-link reload، القائمة وEscape والتركيز وskip link.

أخطاء ظهرت أثناء التطوير:

1. استيراد ملف خط غير موجود `latin.css`: كشفه build، وصُحح إلى مدخل الحزمة.
2. Shift+Tab عند أول عنصر dialog لم يحقق حصر التركيز المطلوب: أضفنا معالجة
   حدود التنقل ثم أعدنا اختبار المتصفح؛ لم نخفف assertion.
3. تعلقت عمليات اختبار داخل sandbox وظهر Vitest worker timeout؛ أعدنا التنفيذ
   بإذن خارج sandbox. لا تُحسب نتيجة تشغيل متعطل كنجاح.

راجع قسم نتائج التحقق أدناه للنتيجة النهائية. الصور في `frontend/test-results/`
مولّدة ومحلية وغير مضافة إلى Git. تمت مراجعة صور 390 و1440px بصريًا.

## الأمان وحدود الإثبات

لا توجد مكتبة Supabase أو tokens أو API calls أو `.env` في الواجهة. صفحات Auth
لا تجمع البريد أو كلمة المرور الآن. مستقبلاً كل VITE_* يصل للمتصفح، لذلك لا
يجوز وضع service role أو Storage key أو DATABASE_URL أو AI key فيه. لا تُحمّل
إعدادات backend من frontend. React route guards ستكون لتجربة الاستخدام فقط؛
FastAPI وRLS يبقيان مرجع الصلاحية.

Playground وPublish وConversations معطلة. لا توجد بيانات حساب وهمية ولا نجاح حفظ
مزيف. الاختبارات الحالية لا تثبت Supabase isolation ولا جاهزية features أو
Safari/Firefox؛ الربط الحقيقي والفحص عبر متصفحات إضافية ما زالا مؤجلين.

## أسئلة للتأكد من الفهم

1. ما الفرق بين `main.tsx` و`Shell.tsx`؟
2. لماذا استخدمنا ButtonLink للتنقل بدل تنفيذ POST من الزر؟
3. كيف يحافظ Outlet على sidebar عند الانتقال بين الصفحات؟
4. لماذا لا يكفي نجاح build لإثبات صحة تركيز لوحة المفاتيح على الموبايل؟
5. لماذا لا تعتبر صفحة frontend مخفية عن المستخدم حماية لبيانات مالك آخر؟

تمرين: افتح القائمة بعرض 390px، تنقل باستخدام Tab ثم Shift+Tab وEscape، ثم
غيّر العرض إلى 1440px وهي مفتوحة. تتبع السلوك في Shell واكتب أي اختبار سيفشل
إذا حُذفت معالجة حدود التركيز. لا تغيّر backend أو تبدأ UI-03 أثناء المراجعة.

## نتائج التحقق

التشغيل النهائي بتاريخ 2026-10-17 انتهى بـexit code 0:

| الفحص | النتيجة الفعلية |
| --- | --- |
| `npm run typecheck` | PASS، بما يشمل ملفات الاختبار والإعدادات |
| `npm run lint` | PASS دون تحذيرات lint |
| `npm test` | 13 passed، لا skipped |
| `npm run build` | PASS؛ ظهر تنبيه أداء bundler فقط |
| `npm run test:browser` | 6 passed في Chromium، لا skipped |
| مراجعة 390 و1440px | الصور فُحصت بصريًا؛ الاختبارات تغطي أيضًا 320 و768 |
| فحص أسرار شائعة في source/tests/build | 31 ملفًا فُحصت، لا مطابقات؛ ليس ضمانًا مطلقًا لكل شكل سر |
| `git diff --check` وignore | PASS؛ node_modules/dist/test-results/.env مستثناة |

تحذير NO_COLOR/FORCE_COLOR يؤثر على ألوان مخرجات الاختبار فقط. لم نُشغّل
اختبارات backend أو Supabase لأن هذا الجزء لم يعدلها. لم يحدث commit أو push.
ملفات AGENTS.md وDocker والمهارات الموجودة مسبقًا لم تُعدّل ضمن هذا العمل.

UI-03 لا يبدأ حتى مراجعة المطوّر لهذا الجزء. قبلها يجب فهم أن Router يبدل
المحتوى، والمكونات تعرض الحالة، بينما إثبات الهوية والصلاحيات يحتاج الربط الحقيقي.

## UI-03 — Supabase Authentication (2026-10-17)

هذا القسم يصف التنفيذ الجديد ويحل محل حدود UI-02 المتعلقة بعدم وجود Auth.
تمت الموافقة على بدء UI-03؛ لم نبدأ UI-04 أو Phase 3. المسار `/` محجوز لصفحة
تسويق مستقبلية، `/assistants` لوحة المالك المحمية، و`/dev/dashboard` معاينة
تطوير فقط تُحذف من production bundle. صفحات إنشاء/تعديل المساعد والمعرفة
ما زالت placeholders ولا تنفذ عمليات backend.

### كيف تعمل المصادقة؟

البريد وكلمة المرور ينتقلان من `AuthPage` إلى `AuthStore.authenticate` ثم
`client.ts` الذي يستدعي Supabase JS: `signInWithPassword` أو `signUp`.
عند النجاح مع session، يخزن SDK الجلسة في sessionStorage ويتلقى store أحداث
الجلسة. `RequireOwner` يسمح بعرض Shell وينتقل المستخدم إلى `/assistants`.
إن نجح التسجيل دون session، نعرض رسالة الخطوة التالية ولا ندّعي أن المستخدم
دخل. إعداد تأكيد البريد يبقى كما هو في Supabase؛ لا نعدله ولا نضيف callback.

عند تحميل الصفحة، يبدأ AuthProvider الاشتراك في أحداث SDK وقراءة `getSession`.
واجهة loading تمنع عرض محتوى المالك قبل اكتمال القراءة. رقم revision يمنع
نتيجة bootstrap قديمة من استبدال جلسة أحدث. لا نستدعي عمليات SDK async من داخل
callback الأحداث لتجنب مشاكل قفل Auth. ينظف effect الاشتراك عند الإزالة.

SDK مسؤول عن refresh token وإعادة التجديد. عند وصول جلسة جديدة يتغير موعد
انتهائها في store. إذا انتهت قبل التجديد، نزيل session ونطلب الدخول؛ ظهور
جلسة جديدة صالحة يسمح بالعودة. getSession المحلي ليس إثبات صلاحية من الخادم:
في UI-04 ستكون FastAPI مسؤولة عن التحقق من Bearer token وRLS عن البيانات.

لا نرسل access token إلى backend في UI-03. لاحقًا يجب أخذ token الحالي من SDK
وقت الطلب، وليس حفظ نسخة قديمة عند تحميل module؛ ثم إرساله في Authorization
فقط إلى FastAPI المعتمد. لا ترسل owner_id أو user_metadata كدليل صلاحية.

### شرح الملفات الجديدة والتغييرات

| الملف تحت `frontend/` | الدور |
| --- | --- |
| `src/auth/config.ts` | `publicAuthConfig`: يتحقق من HTTPS وpublishable/anon key؛ Vite يستعمله قبل تضمين القيم في bundle |
| `src/auth/client.ts` | `createAuthPort`: عميل SDK واحد، تخزين خاص بالمشروع، مهلة 20 ثانية لكل fetch، وتسجيل خروج local |
| `src/auth/store.ts` | `AuthStore`: حالة loading/ready/unconfigured، session وbusy/error وepoch؛ يمنع نتائج استعادة قديمة وأحداث خروج متأخرة |
| `src/auth/context.ts` | Context وuseAuth باستخدام useSyncExternalStore للاشتراك في snapshot ثابتة حتى التحديث |
| `src/auth/AuthProvider.tsx` | lifecycle للاشتراك، RequireOwner، ورسائل تعذر الإعداد |
| `src/auth/errors.ts` | تحويل code/status لرسائل آمنة بدل عرض تفاصيل المزود أو secrets |
| `src/auth/AuthPage.tsx` | نموذج login/register، validation، password visibility، busy وconfirmation/error states |
| `src/auth/auth.module.css` | شاشة عمودين وفق Figma، تتحول لنموذج عمودي على الموبايل |
| `src/main.tsx` | تهيئة store مرة واحدة مع فشل آمن إن منع المتصفح sessionStorage |
| `src/app/routes.tsx` | حجز root وحماية المسارات وتجميع preview تحت شرط DEV |
| `src/app/Shell.tsx` | روابط لوحة المالك وأزرار logout على desktop/mobile |
| `src/pages/Pages.tsx` | تعديل copy حتى يميز تسجيل الدخول الحقيقي عن بيانات المساعدين غير المربوطة |
| `.env.example` | أسماء إعدادات عامة فقط، دون مفاتيح فعلية |
| `vite.config.ts` | فحص الإعدادات وعزل cache حسب mode |
| `tests/auth-fixtures.ts`, `tests/auth.test.tsx` | جلسات وهمية واختبارات races والحماية والنماذج |
| `tests/browser/auth-helpers.ts`, `tests/browser/auth.spec.ts` | اختبار SDK الحقيقي باستجابات HTTP محكومة، وليس Supabase حيًا |

### الخروج وتبديل الحساب

`logout` يزيل session من حالة React فورًا قبل انتظار الشبكة. subtree المحمي
يُفك، فتختفي مدخلات المالك. عند اختلاف user.id يتغير key المبني على id وepoch،
لذلك لا تنتقل حالة المكونات إلى حساب آخر. اختبرنا ذلك بحقل خاص بالمالك A ثم
تبديله إلى B والتأكد أنه فارغ. لا يوجد cache بيانات أو fetch للمساعدين بعد؛
عند إضافتهما يجب إلغاء الطلبات القديمة ورفض نتائجها، وليس الاكتفاء بتغيير key.

الخروج يستخدم `scope: local` ولا يخرج جميع الأجهزة. إذا فشلت الشبكة، تنظف
طبقة التخزين المفاتيح المحددة لهذا المشروع فقط، وتمنع كتابة refresh متأخر،
وتحتفظ بعلامة خروج خالية من الأسرار تمنع الاستعادة بعد reload. تظهر رسالة أن
الخروج المحلي تم لكن إلغاء الجلسة على الخادم لم يتأكد. JWT الصادر قد يبقى صالحًا
حتى انتهاء صلاحيته؛ لا ندعي إلغاءه فوريًا.

sessionStorage ليس حماية من XSS، ونسخ التبويب/استعادة المتصفح أو أحداث SDK
لا تعني عزلًا مطلقًا بين التبويبات. الحماية الحقيقية للبيانات تبقى FastAPI/RLS.
لا نستخدم sessionStorage.clear() الذي قد يحذف بيانات غير مرتبطة بالتطبيق.

### الاختبارات الفعلية والحدود

- TypeScript وOxlint وproduction build: PASS.
- Vitest: **30 passed**، تشمل UI-02 المعدلة وUI-03؛ لا skipped.
- Playwright/Chromium: **13 passed**؛ login/reload/logout، فشل revocation،
  registration بدون session، invalid credentials، المسارات والأحجام والكيبورد.
- تمت معاينة صور login 1440px وregister 390px ومقارنة التصميم؛ الأيقونات المحلية
  موجودة وبأبعادها الأصلية. حذف Google/Full name/Recovery/روابط سياسة غير موجودة
  قرار نطاق، وليست ميزات مفقودة بالغلط. نموذج المحادثة ثابت وموسوم مثالًا.
- فحص bundle أكد غياب dev/dashboard، وفحص أنماط الأسرار لم يجد تطابقًا.
- ظهر تحذير bundle بحجم ~520.6 kB (~151.6 kB gzip)، وهو تحسين أداء مؤجل.
- EBUSY في cache حُل بعزل Vite mode للاختبارات. اختبار خطأ Auth احتاج ترويسة
  x-supabase-api-version المكشوفة عبر CORS حتى يعالج SDK code كما في الخدمة.
- **لم ننفذ تسجيل دخول حي أو نغير Supabase**. نجاح mocks لا يثبت إعداد المشروع
  أو سياسة البريد أو live RLS؛ خطوات التجربة اليدوية موجودة في frontend/README.

أوامر الفحص نفسها في قسم UI-02، والإعداد الجديد: انسخ `.env.example` إلى
`.env.local` فقط إن لم يكن موجودًا، ثم ضع URL وpublishable key العامين للمشروع.
لا تنقل backend/.env. كل VITE_* يصل إلى المتصفح. إعادة تشغيل Vite لازمة بعد
تغيير الإعدادات. بيانات test-only الموجودة في tests ليست حسابات أو مفاتيح حية.

### أسئلة UI-03 وتمرين

1. لماذا يختلف `/assistants` عن `/dev/dashboard` من ناحية الحماية؟
2. ما الفرق بين نجاح signUp ووجود session فعلي؟
3. كيف يمنع revision نتيجة getSession قديمة من إرجاع حساب سابق؟
4. لماذا نزيل subtree قبل اكتمال signOut عبر الشبكة؟
5. لماذا لا تكفي RequireOwner أو user.id الموجودة في browser لحماية قاعدة البيانات؟

تمرين: شغّل اختبارات المتصفح وراجع سيناريو failed sign-out؛ تتبع إزالة التخزين
وإعادة تحميل `/assistants`. اشرح أي طبقة تمنع رجوع المحتوى وأي ضمان لا يمكنها
تقديمه عن صلاحية JWT على الخادم. لا تغيّر إعدادات Supabase أثناء التمرين.

المراجع: [Auth events](https://supabase.com/docs/reference/javascript/auth-onauthstatechange)،
[signOut](https://supabase.com/docs/reference/javascript/auth-signout)،
[signUp](https://supabase.com/docs/reference/javascript/auth-signup).
UI-03 جاهزة للمراجعة المحلية. UI-04 متوقفة حتى مراجعة المطوّر.

## UI-04 — ربط المساعدين بالـAPI (2026-10-18)

### ماذا تغير؟
أصبحت قائمة المساعدين والإنشاء وحفظ إعدادات الـdraft متصلة بعقود FastAPI الموجودة. أكّد المطوّر نجاح تجربة Auth الحية السابقة. هذه المرحلة تدعم FR-001/002 وAC-001/002/003/018؛ ربط المعرفة ضمن AC-003 مؤجل إلى UI-05.

### الملفات والمسؤوليات
- `frontend/src/assistants/api.ts`: أنواع Configuration وAssistant ودالة assistantApi. تستقبل AuthStore وAbortSignal، وتُرجع عمليات list/get/create/update. تستخدم fetch دون مكتبة جديدة، وتتعامل مع 401 و404 و422 برسائل آمنة. مهلة الطلب 20 ثانية، ولا توجد إعادة تلقائية لعمليات الكتابة.
- `frontend/src/assistants/Assistants.tsx`: AssistantList تدير التحميل والخطأ والفراغ؛ AssistantEditor يعيد إنشاء Editor عند تغيّر المساعد. Editor يحمل الإعدادات ويحفظ الحقول المتغيرة فقط ويحفظ المدخلات عند الخطأ. قفل synchronous يمنع إرسال حفظ ثانٍ أثناء الأول.
- `frontend/src/assistants/assistants.module.css`: بطاقات متجاوبة وتخطيط عمودين يتحول إلى عمود واحد على الشاشات الصغيرة، باستخدام مكونات وألوان المشروع.
- `frontend/src/auth/store.ts`: accessToken يطلب الجلسة الحالية من SDK ثم يتحقق من تطابق المالك وepoch وصلاحية الجلسة. لا توجد نسخة توكن مستقلة مخزنة في صفحة المساعد.
- `frontend/src/auth/context.ts`: يتيح AuthStore لطبقة الاتصال. RequireOwner الموجود يعيد تركيب شجرة المالك عند تغيّر الحساب، فيمسح المدخلات والبيانات القديمة.
- `frontend/src/app/routes.tsx`: ربط الشاشات الفعلية؛ تبويب Knowledge يبقى placeholder.
- `frontend/vite.config.ts`: proxy محلي من /api إلى FastAPI على 8000؛ لا حاجة لتعديل CORS أو قاعدة البيانات لهذه التجربة.

### مسار حفظ الإعدادات
النموذج → assistantApi.update → accessToken → PATCH /api/assistants/{id} → Vite proxy → FastAPI → تحقق Supabase Auth → service → repository → SQLAlchemy/PostgreSQL وRLS → الرد → رسالة Draft saved.

الواجهة لا ترسل owner_id. حراسة React تمنع عرض بيانات جلسة سابقة، لكنها ليست بديلًا عن تفويض FastAPI وRLS. حتى لو تأخر رد لحساب A بعد الانتقال إلى B، يُرفض الرد بواسطة فحص owner/epoch، ويُلغى الطلب عند إزالة الصفحة.

### قرارات التصميم وحدوده
لا نستخدم خيارات ثابتة للدور والنبرة لأن العقد يقبل نصوصًا حرة. نحفظ colors.primary وcolors.accent مع الحفاظ على مفاتيح أخرى موجودة. لا ننشئ وصفًا إضافيًا غير مدعوم. المعاينة شكلية وليست Playground. المغادرة المتعمدة للنموذج تفقد التغييرات غير المحفوظة؛ فشل الحفظ يبقيها. تعطل الشبكة بعد POST قد يعني أن الخادم حفظ الطلب بالفعل، لذلك الرسالة تطلب مراجعة القائمة قبل إعادة المحاولة.

### التحقق والتشخيص
اختبارات `tests/assistants.test.tsx` تغطي قائمة مساعدين مستقلين، PATCH محدودًا بالحقول المتغيرة، فشل الحفظ، تبديل المالك أثناء الطلب، 401 دون إعادة كتابة، 404 وحدود النموذج. `tests/browser/assistants.spec.ts` يستخدم المتصفح وSDK مع HTTP responses مضبوطة لاختبار الإنشاء والتعديل وإعادة التحميل، ويتأكد من عدم إرسال owner_id. هذه ليست تجربة قاعدة بيانات حية.

شغّل من frontend: `npm.cmd run typecheck`، `npm.cmd run lint`، `npm.cmd test`، `npm.cmd run test:browser`، `npm.cmd run build`.

إذا ظهر خطأ اتصال، تأكد من تشغيل FastAPI على 8000 وVite على 5173. إذا ظهر 401 سجّل الدخول من جديد؛ لا تنسخ التوكن إلى تقارير الأخطاء. إذا ظهر 404 تأكد من المساعد والحساب الحالي دون تخفيف RLS. تفاصيل التشغيل في frontend/README.md.

### أسئلة للفهم
1. ما الفرق بين بيانات النموذج ونسخة original؟
2. لماذا نرسل PATCH بالحقول المتغيرة فقط؟
3. لماذا لا نسمح بإرسال owner_id؟
4. ماذا يحدث لطلب قيد التنفيذ عند تبديل الحساب؟
5. لماذا لا تُعد إعادة POST تلقائيًا آمنة بعد انقطاع الشبكة؟

تمرين: حاكِ فشل PATCH برمز 503، تحقق من بقاء المدخلات، ثم أعد استجابة ناجحة وتأكد أن رسالة الحفظ تظهر مرة واحدة. لا تغيّر إعدادات قاعدة البيانات لهذا التمرين.

قبل UI-05 راجع تجربة إنشاء مساعدين وتعديل أحدهما على حسابك الحقيقي، ثم تبديل الحساب. تبقى المعرفة وRAG والنشر خارج هذا التغيير.

### نتائج UI-04 النهائية
- TypeScript typecheck وOxlint وproduction build: PASS.
- Vitest: 37 passed، دون skips، بعد إعادة التشغيل خارج sandbox بسبب worker startup timeout.
- Playwright: 14 passed؛ أُعيد اختبار مسار المساعد وحده بعد تحسين المسافات: 1 passed. تمت مراجعة screenshot الهاتف والـdesktop؛ لا يوجد تجاوز عرض في الاختبار.
- Build يعطي تحذير حجم JS نحو 524 kB قبل gzip؛ لا يمنع التشغيل.
- مراجعة `git diff --check` ناجحة بعد إزالة أسطر نهاية إضافية. لا dependencies جديدة ولا تعديل backend أو live Supabase، ولا commit/push.
- اختبارات HTTP مضبوطة؛ اختبار إنشاء/تعديل المساعدين على البيئة الحية ينتظر مراجعة المطوّر. نجاح تجربة Auth السابقة مؤكد من المطوّر فقط، وليس نتيجة تشغيل حي جديد هنا.
