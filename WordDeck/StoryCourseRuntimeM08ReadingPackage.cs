using System.Runtime.CompilerServices;

namespace WordDeck;

/// <summary>
/// Governed CE-A1-M08 Reading package. The content is compiled into WordDeck and
/// materialized into the existing local Story/Course package boundary on first normal
/// launch. This deliberately reuses the existing loader/UI/state model instead of
/// creating another course engine.
///
/// RDG0009/RDG0010 are governed first-exposure formative-transfer objects. The current
/// generic Story/Course UI does not yet record exposure at presentation time, so this
/// binding fails closed: those objects are learner-visible formative practice but no
/// fresh-transfer/mastery/Fast-Track evidence is emitted from this package.
/// </summary>
internal static class StoryCourseRuntimeM08ReadingPackage
{
    internal const string CourseId = "ce-a1-m08-reading-runtime";
    internal const string ModuleId = "ce-a1-m08";
    internal const string PackageFileName = "ce-a1-m08-reading.governed.story-course.json";

    internal const string SourceId = "11iFfRtWDreAWRIhjf7i6q698K2sQ5f0uY0Qmn5uPOLE";
    internal const string SourceRevision = "ANLCKQly-WHy9rup0FPMbxLz7Lr0hC9cb6WgnJvGdhUUnAEzN4QO7P8TzSAYCam_yYH0gH80nLgDLpHC-7WUiRxzlPEcdaSKogMYJ2t4bA";
    internal const string QaId = "1jdI1PFNlq165HTB6cvZx0B7qrWN28OYhsxy4tsjITyw";
    internal const string QaRevision = "ANLCKQkJydd2dKedwIeFlUpAWFbDPxAnvYdvrV5UL8NqRf1msINij-0rbBD1fVeOtFpOdr2oodYUtHR1jKvmm-VKeVra5uhEFupY1cP1-A";
    internal const string IntegrationId = "1VchhW9t-sDGslLWCdNKfsLsw9F0rg7meEbaXksdliNU";
    internal const string IntegrationRevision = "ANLCKQmhYg9efB9PrIgVu3T4rgWUESgNPuy66kFj7KeHQVq6dW-dIqWb8427iEnjFu6O-gB10Iw3DByxqT3YwKgdEWWlPsBFtsp6wb9KAw";
    internal const string TargetLanguageIntegrationId = "1wtGgU0QrqVYwDLZhHLJrW0ZOuuYAcVn62Kl6teUsbAw";
    internal const string TargetLanguageIntegrationRevision = "ANLCKQmbLttc6qnkUl8Y9vQ-GZMUPlcIaNEVXQGsxa0tEn6QIEDUmCbr3_hyNuXWGwgaOKEWHvJB4Zb571yQrIrVZbYh_pINtTs-KMUWkQ";

    private const string RightsHold =
        "HOLD_PENDING_CANONICAL_CONTENT_PROVENANCE_MANIFEST_AND_INDEPENDENT_RIGHTS_REVIEW";

    private sealed record TaskSpec(string Prompt, string[] Accepted, string[] EvidenceTargets);
    private sealed record ObjectSpec(
        string Key,
        string Title,
        string Text,
        string[] PresenceTargets,
        TaskSpec[] Tasks,
        bool FreshTransferCandidate = false);

    internal static StoryCourseManifestContract BuildManifest()
    {
        StoryCourseProvenanceContract provenance = BuildManifestProvenance();
        ObjectSpec[] specs = BuildSpecs();
        StoryCourseObjectiveContract[] objectives = specs
            .SelectMany(BuildObjectives)
            .ToArray();
        StoryCourseUnitContract[] units = specs.Select(BuildUnit).ToArray();

        StoryCourseModuleContract module = new(
            ModuleId,
            "ce-a1",
            "Leisure, Invitations, and What Is Happening Now — Reading",
            objectives,
            units);
        StoryCourseLevelContract level = new(
            "ce-a1",
            "A1",
            "Complete English A1",
            8,
            new[] { module });
        return new StoryCourseManifestContract(
            CourseId,
            "Complete English A1 — M08 Reading — Leisure, Invitations, and What Is Happening Now",
            StoryCourseCurriculumAuthority.ApprovedCurriculum,
            ClaimsCompleteEnglishCourse: false,
            new[] { level },
            provenance);
    }

    internal static string DefaultPackageRoot() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "WordDeck",
        "Courses");

    internal static bool TryInstall(string root, out string status)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(root)) throw new ArgumentException("Package root is required.", nameof(root));
            string fullRoot = Path.GetFullPath(root);
            Directory.CreateDirectory(fullRoot);
            StoryCourseManifestContract manifest = BuildManifest();
            ValidateWithEmptyDictionary(manifest);
            string serialized = StoryCoursePackageLoader.Serialize(manifest);
            _ = StoryCoursePackageLoader.Deserialize(serialized);

            string target = Path.Combine(fullRoot, PackageFileName);
            if (File.Exists(target))
            {
                try
                {
                    StoryCourseManifestContract existing = StoryCoursePackageLoader.Deserialize(File.ReadAllText(target));
                    ValidateWithEmptyDictionary(existing);
                    if (StoryCoursePackageLoader.Serialize(existing).Equals(serialized, StringComparison.Ordinal))
                    {
                        status = "CURRENT";
                        return true;
                    }
                }
                catch
                {
                    // The fixed project-owned path is recoverable. Preserve the prior bytes below.
                }

                string backup = Path.Combine(fullRoot, "ce-a1-m08-reading.governed.story-course.previous.json");
                File.Copy(target, backup, overwrite: true);
            }

            string temp = target + ".tmp." + Guid.NewGuid().ToString("N");
            try
            {
                File.WriteAllText(temp, serialized, new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
                StoryCourseManifestContract roundTrip = StoryCoursePackageLoader.Deserialize(File.ReadAllText(temp));
                ValidateWithEmptyDictionary(roundTrip);
                File.Move(temp, target, overwrite: true);
            }
            finally
            {
                try { if (File.Exists(temp)) File.Delete(temp); } catch { }
            }

            status = "INSTALLED";
            return true;
        }
        catch (Exception ex)
        {
            status = "FAILED: " + ex.Message;
            return false;
        }
    }

    internal static void LogBootstrapFailure(string message)
    {
        try
        {
            string root = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "WordDeck",
                "Logs");
            Directory.CreateDirectory(root);
            File.AppendAllText(
                Path.Combine(root, "m08-reading-package-bootstrap.log"),
                DateTimeOffset.UtcNow.ToString("O") + " " + message + Environment.NewLine,
                new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        }
        catch
        {
            // A diagnostic write must never make WordDeck fail to start.
        }
    }

    private static void ValidateWithEmptyDictionary(StoryCourseManifestContract manifest)
    {
        DictionaryPackage dictionary = new()
        {
            Id = "dictionary.m08.reading.runtime.validation",
            Name = "M08 Reading runtime validation dictionary",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = Array.Empty<DictionaryEntry>()
        };
        StoryCourseContractValidator.Validate(manifest, dictionary);
    }

    private static StoryCourseUnitContract BuildUnit(ObjectSpec spec)
    {
        StoryCourseProvenanceContract provenance = BuildInheritedProvenance();
        string prefix = "ce-a1-m08-" + spec.Key;
        string[] objectiveIds = Enumerable.Range(1, 4)
            .Select(index => $"{prefix}-q{index}-objective")
            .ToArray();
        StoryCourseTargetsContract targets = new(
            Array.Empty<string>(),
            Array.Empty<string>())
        {
            SkillTargets = spec.PresenceTargets
                .Select(target => new StoryCourseSkillTargetReferenceContract(
                    StoryCourseSkillTargetReferenceContract.CourseTargetDomain,
                    target))
                .ToArray()
        };
        string safety = spec.FreshTransferCandidate
            ? "Runtime safety: governed first-exposure object. This generic runtime currently presents it as ordinary formative Reading practice only; no fresh-transfer, protected mastery, Fast Track, Listening, Speaking, Writing, or level-exit evidence is emitted."
            : "Runtime safety: Reading-only formative practice. Exposure, support, reveal, completion, XP, or streak do not establish mastery. No protected mastery, Fast Track, Listening, Speaking, Writing, or level-exit evidence is emitted.";
        StoryCourseNarrativeContract narrative = new(
            prefix + "-text",
            StoryCourseNarrativeKind.Story,
            spec.Text + Environment.NewLine + Environment.NewLine + safety,
            Array.Empty<string>(),
            provenance);
        StoryCourseComprehensionTaskContract[] tasks = spec.Tasks
            .Select((task, index) => new StoryCourseComprehensionTaskContract(
                $"{prefix}-q{index + 1}",
                StoryCourseComprehensionKind.BoundedResponse,
                task.Prompt,
                new[] { objectiveIds[index] },
                task.Accepted))
            .ToArray();
        return new StoryCourseUnitContract(
            prefix,
            ModuleId,
            "CE-A1-M08-" + spec.Key.ToUpperInvariant() + " — " + spec.Title,
            objectiveIds,
            targets,
            new[] { narrative },
            tasks,
            Array.Empty<StoryCourseProductiveTaskContract>(),
            Checkpoint: null,
            provenance);
    }

    private static IEnumerable<StoryCourseObjectiveContract> BuildObjectives(ObjectSpec spec)
    {
        string prefix = "ce-a1-m08-" + spec.Key;
        for (int index = 0; index < spec.Tasks.Length; index++)
        {
            TaskSpec task = spec.Tasks[index];
            var channels = new List<string> { "reading-formative" };
            channels.AddRange(task.EvidenceTargets.Select(target => "course-target:" + target));
            if (spec.FreshTransferCandidate)
                channels.Add("fresh-transfer-candidate-fail-closed");
            yield return new StoryCourseObjectiveContract(
                $"{prefix}-q{index + 1}-objective",
                $"{spec.Title}: Reading task Q{index + 1}; preserve only pre-bound formative evidence.",
                channels);
        }
    }

    private static StoryCourseProvenanceContract BuildManifestProvenance() => new(
        StoryCourseContentOrigin.WordDeckAuthored,
        $"Drive:{SourceId}@{SourceRevision}",
        "1.1",
        RightsHold,
        $"Independent QA Drive:{QaId}@{QaRevision}; governed Reading integration Drive:{IntegrationId}@{IntegrationRevision}; " +
        $"governed M08 Target Language integration Drive:{TargetLanguageIntegrationId}@{TargetLanguageIntegrationRevision}. " +
        "Commercial/public redistribution remains HOLD. RDG0009/RDG0010 are fail-closed to ordinary formative practice until exact first-exposure runtime evidence is supported.");

    private static StoryCourseProvenanceContract BuildInheritedProvenance() => new(
        StoryCourseContentOrigin.WordDeckAuthored,
        "ce-a1-m08-reading-runtime-governed",
        "1.1",
        RightsHold,
        "Exact governed source/QA/integration pins are carried by the enclosing manifest provenance.");

    private static TaskSpec T(string prompt, string[] accepted, params string[] evidenceTargets) =>
        new(prompt, accepted, evidenceTargets);

    private static ObjectSpec[] BuildSpecs() => new[]
    {
        new ObjectSpec(
            "rdg0001",
            "Riverside Saturday Activity Day",
            "Riverside Saturday Activity Day\n" +
            "10:00 Park football — Riverside Park. Beginners welcome.\n" +
            "11:30 Swimming session — North Pool.\n" +
            "13:00 Quiet reading hour — Riverside Library.\n" +
            "15:00 Dance class — Community Hall.\n" +
            "17:30 Music club — Community Hall. Bring no equipment; just come and listen.",
            new[] { "CE-A1-M08-TL0029", "CE-A1-M08-TL0030", "CE-A1-M08-TL0032", "CE-A1-M08-TL0033", "CE-A1-M08-TL0035", "CE-A1-M08-TL0039" },
            new[]
            {
                T("What is the main purpose of the text? Enter A, B, or C. A) to list Saturday leisure activities; B) to describe one person’s job; C) to explain yesterday’s weather", new[] { "a", "to list saturday leisure activities" }),
                T("Which activity is at Riverside Park?", new[] { "park football" }),
                T("Where is the swimming session?", new[] { "north pool" }),
                T("Which activity starts at 15:00?", new[] { "the dance class", "dance class" })
            }),
        new ObjectSpec(
            "rdg0002",
            "What everyone is doing now",
            "Group message — 18:20\n" +
            "Maya: I’m reading in the café right now.\n" +
            "Leo: I’m not playing football. I’m listening to music at home.\n" +
            "Ana: Tom is swimming at North Pool. I’m waiting for him outside.\n" +
            "Maya: What are you doing, Leo?\n" +
            "Leo: I’m making tea now.",
            new[] { "CE-A1-M08-TL0001", "CE-A1-M08-TL0003", "CE-A1-M08-TL0007", "CE-A1-M08-TL0013", "CE-A1-M08-TL0014", "CE-A1-M08-TL0015", "CE-A1-M08-TL0033", "CE-A1-M08-TL0035" },
            new[]
            {
                T("Where is Maya now?", new[] { "in the café", "the café", "café" }),
                T("Is Leo playing football now?", new[] { "no" }, "CE-A1-M08-TL0007"),
                T("Which line asks Leo about his action now?", new[] { "what are you doing leo", "what are you doing, leo", "what are you doing, leo?" }, "CE-A1-M08-TL0013"),
                T("What is Tom doing?", new[] { "he is swimming", "swimming" })
            }),
        new ObjectSpec(
            "rdg0003",
            "Every Friday and today",
            "Friday Running Club\n" +
            "We usually run in Riverside Park on Fridays at 18:00. We meet at the park gate.\n" +
            "Today is different. It is raining, so the group is not running in the park. We are meeting at Blue Cup Café at 18:00 and listening to music there.",
            new[] { "CE-A1-M08-TL0015", "CE-A1-M08-TL0016", "CE-A1-M08-TL0031", "CE-A1-M08-TL0035", "CE-A1-M08-TL0040" },
            new[]
            {
                T("What does the club usually do on Fridays?", new[] { "it runs in riverside park", "runs in riverside park" }),
                T("What is the group doing today instead?", new[] { "meeting at blue cup café and listening to music", "meeting at blue cup cafe and listening to music" }, "CE-A1-M08-TL0015", "CE-A1-M08-TL0016"),
                T("Does the meeting time change today?", new[] { "no", "no it is still 18:00", "no. it is still 18:00." }),
                T("Which phrase marks the regular routine: ‘usually run’ or ‘are meeting’?", new[] { "usually run" }, "CE-A1-M08-TL0016")
            }),
        new ObjectSpec(
            "rdg0004",
            "Three hobby profiles",
            "Nora: I like reading and watching films. I don’t like running.\n" +
            "Sam: I love swimming and I like playing football. I hate dancing.\n" +
            "Ivo: I love listening to music. I like dancing, but I hate swimming.",
            new[] { "CE-A1-M08-TL0017", "CE-A1-M08-TL0018", "CE-A1-M08-TL0019", "CE-A1-M08-TL0029", "CE-A1-M08-TL0030", "CE-A1-M08-TL0032", "CE-A1-M08-TL0033", "CE-A1-M08-TL0034", "CE-A1-M08-TL0035" },
            new[]
            {
                T("Who likes reading?", new[] { "nora" }, "CE-A1-M08-TL0017"),
                T("Who loves swimming?", new[] { "sam" }, "CE-A1-M08-TL0018"),
                T("Who hates dancing?", new[] { "sam" }, "CE-A1-M08-TL0019"),
                T("Which two people have different opinions about swimming?", new[] { "sam and ivo", "ivo and sam" })
            }),
        new ObjectSpec(
            "rdg0005",
            "Cinema invitation and final arrangement",
            "Kai: Would you like to watch a film on Saturday?\n" +
            "Mira: Yes, I’d love to.\n" +
            "Kai: Great. Let’s meet at Star Cinema at 17:40.\n" +
            "Mira: What time does the film start?\n" +
            "Kai: 18:10. We can have tea at Corner Café after the film.\n" +
            "Mira: Sounds good. See you at Star Cinema at 17:40.",
            new[] { "CE-A1-M08-TL0021", "CE-A1-M08-TL0023", "CE-A1-M08-TL0025", "CE-A1-M08-TL0028", "CE-A1-M08-TL0034", "CE-A1-M08-TL0036", "CE-A1-M08-TL0040" },
            new[]
            {
                T("What does Kai do in the first message?", new[] { "he invites mira to watch a film", "invites mira to watch a film" }, "CE-A1-M08-TL0021"),
                T("Does Mira accept the invitation?", new[] { "yes" }, "CE-A1-M08-TL0023"),
                T("Where and when will they meet?", new[] { "at star cinema at 17:40", "star cinema at 17:40" }, "CE-A1-M08-TL0025"),
                T("Which final line confirms the meeting arrangement?", new[] { "see you at star cinema at 17:40", "see you at star cinema at 17:40." }, "CE-A1-M08-TL0028")
            }),
        new ObjectSpec(
            "rdg0006",
            "Rainy-day plan change",
            "Original plan: Let’s go for a walk in Green Park at 16:00.\n" +
            "Update at 15:15: It is raining hard. The walk is off.\n" +
            "Rosa: Can you meet at Maple Café instead?\n" +
            "Ben: Yes. Where can we meet inside?\n" +
            "Rosa: Near the front window at 16:00. After tea, let’s go to the cinema next door.",
            new[] { "CE-A1-M08-TL0020", "CE-A1-M08-TL0022", "CE-A1-M08-TL0027", "CE-A1-M08-TL0036", "CE-A1-M08-TL0038", "CE-A1-M08-TL0040" },
            new[]
            {
                T("What was the first leisure plan?", new[] { "go for a walk in green park", "a walk in green park" }, "CE-A1-M08-TL0038"),
                T("Why is the walk not happening?", new[] { "because it is raining hard", "it is raining hard" }),
                T("Which question asks about the meeting place?", new[] { "where can we meet inside", "where can we meet inside?" }, "CE-A1-M08-TL0027"),
                T("What do Rosa and Ben plan to do after tea?", new[] { "go to the cinema next door", "the cinema next door" })
            }),
        new ObjectSpec(
            "rdg0007",
            "Quick weekend event board",
            "WEEKEND BOARD\n" +
            "Book Circle — Saturday 11:00 — West Library — read and talk about a short story.\n" +
            "Afternoon Film — Saturday 15:30 — Moon Cinema — family comedy.\n" +
            "Live Music — Saturday 19:00 — Market Hall — local concert.\n" +
            "Sunday Swim — Sunday 10:00 — City Pool — open session.",
            new[] { "CE-A1-M08-TL0033", "CE-A1-M08-TL0029", "CE-A1-M08-TL0030", "CE-A1-M08-TL0034", "CE-A1-M08-TL0035", "CE-A1-M08-TL0036", "CE-A1-M08-TL0037" },
            new[]
            {
                T("Which listing is for reading a story?", new[] { "book circle" }, "CE-A1-M08-TL0033"),
                T("Where is the Saturday film?", new[] { "moon cinema" }),
                T("Which listing is a concert?", new[] { "live music" }),
                T("When is the swim session?", new[] { "sunday at 10:00", "sunday 10:00" })
            }),
        new ObjectSpec(
            "rdg0008",
            "Live leisure update",
            "Niko and Sara usually play football in Oak Park on Sunday afternoons.\n" +
            "Today Niko is not playing. He is sitting in River Café and reading.\n" +
            "Sara: Let’s meet at River Café at 16:30 and listen to music.\n" +
            "Niko: Sounds good.\n" +
            "Sara: Great. See you there at 16:30.",
            new[] { "CE-A1-M08-TL0008", "CE-A1-M08-TL0015", "CE-A1-M08-TL0016", "CE-A1-M08-TL0020", "CE-A1-M08-TL0023", "CE-A1-M08-TL0025", "CE-A1-M08-TL0039", "CE-A1-M08-TL0040" },
            new[]
            {
                T("What do Niko and Sara usually do on Sunday afternoons?", new[] { "play football in oak park" }, "CE-A1-M08-TL0016"),
                T("What is Niko doing today?", new[] { "sitting in river café and reading", "sitting in river cafe and reading" }),
                T("Does Niko accept Sara’s new plan?", new[] { "yes" }, "CE-A1-M08-TL0023"),
                T("Where and when will they meet?", new[] { "river café at 16:30", "river cafe at 16:30" }, "CE-A1-M08-TL0025")
            }),
        new ObjectSpec(
            "rdg0009",
            "Fresh transfer A: Harbour Activity Day",
            "Harbour Activity Day — first view only\n" +
            "10:30 Reading corner — Harbour Library.\n" +
            "12:00 Football skills — Harbour Field.\n" +
            "14:00 Music room — Harbour Centre.\n" +
            "Message from Lina at 09:40: ‘Would you like to come to the music room with me? Let’s meet at Harbour Café at 13:40.’\n" +
            "Pavel: ‘Yes, great. See you at Harbour Café at 13:40.’",
            new[] { "CE-A1-M08-TL0020", "CE-A1-M08-TL0021", "CE-A1-M08-TL0023", "CE-A1-M08-TL0025", "CE-A1-M08-TL0029", "CE-A1-M08-TL0033", "CE-A1-M08-TL0035" },
            new[]
            {
                T("Which activity starts at 12:00?", new[] { "football skills" }),
                T("What is Lina asking Pavel to do?", new[] { "come to the music room with her", "go to the music room with her" }, "CE-A1-M08-TL0021"),
                T("Does Pavel accept?", new[] { "yes" }, "CE-A1-M08-TL0023"),
                T("Where and when will they meet?", new[] { "harbour café at 13:40", "harbour cafe at 13:40" }, "CE-A1-M08-TL0025")
            },
            FreshTransferCandidate: true),
        new ObjectSpec(
            "rdg0010",
            "Fresh transfer B: Park concert change",
            "Park Concert Update — first view only\n" +
            "The 18:00 concert is not in Hill Park today. The band is playing at North Hall instead.\n" +
            "Mila: ‘Can you come to North Hall?’\n" +
            "Owen: ‘Sorry, I can’t at 18:00. I’m working until 18:15.’\n" +
            "Mila: ‘Where can we meet after the concert?’\n" +
            "Owen: ‘At North Café at 20:00.’\n" +
            "Mila: ‘Good. See you at North Café at 20:00.’",
            new[] { "CE-A1-M08-TL0001", "CE-A1-M08-TL0003", "CE-A1-M08-TL0015", "CE-A1-M08-TL0022", "CE-A1-M08-TL0024", "CE-A1-M08-TL0027", "CE-A1-M08-TL0028", "CE-A1-M08-TL0039", "CE-A1-M08-TL0040", "CE-A1-M08-TL0037" },
            new[]
            {
                T("Where is the concert today?", new[] { "north hall" }),
                T("Why can’t Owen come at 18:00?", new[] { "he is working until 18:15", "working until 18:15" }, "CE-A1-M08-TL0001"),
                T("Which line asks for a meeting place?", new[] { "where can we meet after the concert", "where can we meet after the concert?" }, "CE-A1-M08-TL0027"),
                T("Where and when will Mila and Owen meet?", new[] { "north café at 20:00", "north cafe at 20:00" }, "CE-A1-M08-TL0028")
            },
            FreshTransferCandidate: true)
    };
}

internal static class StoryCourseRuntimeM08ReadingPackageBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        if (!StoryCourseRuntimeM08ReadingPackage.TryInstall(
                StoryCourseRuntimeM08ReadingPackage.DefaultPackageRoot(),
                out string status))
        {
            StoryCourseRuntimeM08ReadingPackage.LogBootstrapFailure(status);
        }
    }
}

internal static class StoryCourseRuntimeM08ReadingPackageSelfTest
{
    internal static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "worddeck-m08-reading-runtime-" + Guid.NewGuid().ToString("N"));
        string courseRoot = Path.Combine(root, "Courses");
        string progressRoot = Path.Combine(root, "Progress");
        string learnerRoot = Path.Combine(root, "Learner");
        Directory.CreateDirectory(courseRoot);

        try
        {
            DictionaryPackage dictionary = new()
            {
                Id = "dictionary.m08.reading.self-test",
                Name = "M08 Reading runtime self-test dictionary",
                SourceLanguage = "en",
                TargetLanguage = "uk",
                Entries = Array.Empty<DictionaryEntry>()
            };
            StoryCourseManifestContract manifest = StoryCourseRuntimeM08ReadingPackage.BuildManifest();
            StoryCourseContractValidator.Validate(manifest, dictionary);

            Require(manifest.CourseId == StoryCourseRuntimeM08ReadingPackage.CourseId,
                "course identity changed");
            Require(manifest.CurriculumAuthority == StoryCourseCurriculumAuthority.ApprovedCurriculum && !manifest.ClaimsCompleteEnglishCourse,
                "bounded M08 package authority/whole-course truth changed");
            Require(manifest.Levels.Count == 1 && manifest.Levels[0].FrameworkLevel == "A1",
                "M08 Reading lost its A1 framework binding");
            StoryCourseModuleContract module = manifest.Levels.Single().Modules.Single();
            Require(module.ModuleId == StoryCourseRuntimeM08ReadingPackage.ModuleId,
                "M08 module identity changed");
            Require(module.Units.Count == 10,
                "expected exactly ten governed Reading objects");
            Require(module.Units.Sum(unit => unit.ComprehensionTasks.Count) == 40,
                "expected exactly forty governed Reading tasks");
            Require(module.Units.All(unit => unit.ProductiveTasks.Count == 0 && unit.Checkpoint is null),
                "Reading package fabricated productive/protected assessment content");

            string[] expectedUnits = Enumerable.Range(1, 10)
                .Select(index => $"ce-a1-m08-rdg{index:0000}")
                .ToArray();
            Require(module.Units.Select(unit => unit.UnitId).SequenceEqual(expectedUnits, StringComparer.Ordinal),
                "RDG0001..RDG0010 runtime identity sequence drifted");
            Require(module.Units.All(unit => unit.Targets.SkillTargets.All(target =>
                    target.Domain == StoryCourseSkillTargetReferenceContract.CourseTargetDomain &&
                    target.TargetRef.StartsWith("CE-A1-M08-TL", StringComparison.Ordinal) &&
                    int.TryParse(target.TargetRef[^4..], out int ordinal) && ordinal is >= 1 and <= 40)),
                "M08 Reading escaped governed TL0001..TL0040 target authority");

            Require(Channels(module, "ce-a1-m08-rdg0002-q2").Contains("course-target:CE-A1-M08-TL0007"),
                "RDG0002 Q2 pre-bound TL0007 evidence mapping was lost");
            Require(Channels(module, "ce-a1-m08-rdg0002-q3").Contains("course-target:CE-A1-M08-TL0013"),
                "RDG0002 Q3 pre-bound TL0013 evidence mapping was lost");
            Require(Channels(module, "ce-a1-m08-rdg0005-q1").Contains("course-target:CE-A1-M08-TL0021") &&
                    Channels(module, "ce-a1-m08-rdg0005-q2").Contains("course-target:CE-A1-M08-TL0023") &&
                    Channels(module, "ce-a1-m08-rdg0005-q3").Contains("course-target:CE-A1-M08-TL0025") &&
                    Channels(module, "ce-a1-m08-rdg0005-q4").Contains("course-target:CE-A1-M08-TL0028"),
                "RDG0005 invitation/arrangement evidence map drifted");
            Require(Channels(module, "ce-a1-m08-rdg0001-q1").SequenceEqual(new[] { "reading-formative" }),
                "empty source evidence mapping was broadened after the learner response");
            Require(module.Objectives
                    .Where(objective => objective.ObjectiveId.Contains("rdg0009", StringComparison.Ordinal) ||
                                        objective.ObjectiveId.Contains("rdg0010", StringComparison.Ordinal))
                    .All(objective => objective.EvidenceChannels.Contains("fresh-transfer-candidate-fail-closed")),
                "RDG0009/RDG0010 no longer fail closed while first-exposure runtime evidence is unsupported");
            Require(module.Objectives.All(objective => objective.EvidenceChannels.All(channel =>
                    !channel.Contains("listening", StringComparison.OrdinalIgnoreCase) &&
                    !channel.Contains("speaking", StringComparison.OrdinalIgnoreCase) &&
                    !channel.Contains("writing", StringComparison.OrdinalIgnoreCase) &&
                    !channel.Contains("mastery", StringComparison.OrdinalIgnoreCase) &&
                    !channel.Contains("fast-track", StringComparison.OrdinalIgnoreCase))),
                "text-only Reading package leaked a forbidden evidence channel");

            Require(manifest.Provenance.SourceId.Contains(StoryCourseRuntimeM08ReadingPackage.SourceId, StringComparison.Ordinal) &&
                    manifest.Provenance.SourceId.Contains(StoryCourseRuntimeM08ReadingPackage.SourceRevision, StringComparison.Ordinal),
                "exact governed Reading source/revision is not pinned");
            Require(manifest.Provenance.Attribution.Contains(StoryCourseRuntimeM08ReadingPackage.QaId, StringComparison.Ordinal) &&
                    manifest.Provenance.Attribution.Contains(StoryCourseRuntimeM08ReadingPackage.QaRevision, StringComparison.Ordinal) &&
                    manifest.Provenance.Attribution.Contains(StoryCourseRuntimeM08ReadingPackage.IntegrationId, StringComparison.Ordinal) &&
                    manifest.Provenance.Attribution.Contains(StoryCourseRuntimeM08ReadingPackage.IntegrationRevision, StringComparison.Ordinal) &&
                    manifest.Provenance.Attribution.Contains(StoryCourseRuntimeM08ReadingPackage.TargetLanguageIntegrationId, StringComparison.Ordinal) &&
                    manifest.Provenance.Attribution.Contains(StoryCourseRuntimeM08ReadingPackage.TargetLanguageIntegrationRevision, StringComparison.Ordinal),
                "runtime provenance lost exact QA/integration/TL pins");
            Require(manifest.Provenance.LicenseOrRights.Contains("HOLD", StringComparison.OrdinalIgnoreCase),
                "commercial/public rights HOLD disappeared");

            Require(StoryCourseRuntimeM08ReadingPackage.TryInstall(courseRoot, out string installStatus) &&
                    installStatus == "INSTALLED",
                "governed package did not install into isolated local package boundary");
            string packagePath = Path.Combine(courseRoot, StoryCourseRuntimeM08ReadingPackage.PackageFileName);
            Require(File.Exists(packagePath), "installed governed package file is missing");
            StoryCoursePackageDiscoveryResult discovery = StoryCoursePackageLoader.Discover(dictionary, new[] { courseRoot });
            Require(discovery.Errors.Count == 0 && discovery.Courses.Count == 1 &&
                    discovery.Courses[0].CourseId == StoryCourseRuntimeM08ReadingPackage.CourseId,
                "installed M08 package is not discoverable through the existing learner runtime boundary");
            Require(StoryCourseRuntimeM08ReadingPackage.TryInstall(courseRoot, out string currentStatus) &&
                    currentStatus == "CURRENT",
                "idempotent install rewrote an unchanged governed package");

            File.WriteAllText(packagePath, "{corrupt", new System.Text.UTF8Encoding(false));
            Require(StoryCourseRuntimeM08ReadingPackage.TryInstall(courseRoot, out string recoveryStatus) &&
                    recoveryStatus == "INSTALLED",
                "corrupt project-owned package could not be recovered safely");
            string backupPath = Path.Combine(courseRoot, "ce-a1-m08-reading.governed.story-course.previous.json");
            Require(File.Exists(backupPath) && File.ReadAllText(backupPath) == "{corrupt",
                "package recovery did not preserve prior bytes outside the discovery pattern");
            StoryCourseManifestContract recovered = StoryCoursePackageLoader.Deserialize(File.ReadAllText(packagePath));
            StoryCourseContractValidator.Validate(recovered, dictionary);

            var progressStore = new StoryCourseRuntimeStateStore(manifest.CourseId, progressRoot);
            StoryCourseProgressContract progress = progressStore.LoadOrCreate(manifest);
            StoryCourseUnitContract firstUnit = module.Units.First();
            StoryCourseComprehensionTaskContract firstTask = firstUnit.ComprehensionTasks.First();
            progress = StoryCourseRuntimeStateStore.RecordBoundedComprehensionSuccess(progress, firstTask);
            progressStore.Save(progress);
            StoryCourseProgressContract reopened = progressStore.LoadOrCreate(manifest);
            StoryCourseObjectiveProgressContract objective = reopened.ObjectiveProgress[firstTask.ObjectiveIds.Single()];
            Require(objective.ComprehensionEvidenceCount == 1 &&
                    objective.MasteryDecision == StoryCourseMasteryDecision.Unknown &&
                    objective.DecisionAuthority is null,
                "Reading completion/reopen fabricated mastery");

            var learnerStore = new LearnerCourseStateStore(learnerRoot);
            var ids = new Queue<string>(new[] { "m08.exposure", "m08.practice" });
            var bridge = new StoryCourseLearnerStateBridge(
                learnerStore,
                () => ids.Dequeue(),
                () => new DateTimeOffset(2026, 9, 13, 6, 0, 0, TimeSpan.Zero));
            StoryCourseUnitContract transferUnit = module.Units.Single(unit => unit.UnitId == "ce-a1-m08-rdg0009");
            bridge.RecordNarrativeExposure(manifest, module.ModuleId, transferUnit.UnitId, transferUnit.DialogueOrStory.Single().ContentId);
            bridge.RecordComprehensionPracticeAttempt(
                manifest,
                module.ModuleId,
                transferUnit.UnitId,
                transferUnit.ComprehensionTasks.First().TaskId,
                correct: true,
                attemptNumber: 1,
                isTransfer: false);
            LearnerCourseState learner = learnerStore.Load();
            Require(learner.EvidenceHistory.Count == 2 && learner.EvidenceHistory.All(item => !item.IsTransferPerformance),
                "fail-closed RDG0009 runtime manufactured fresh-transfer evidence");
            Require(learner.MasteryByObjectiveId.Count == 0 && learner.AdaptiveRouteByPathId.Count == 0,
                "ordinary M08 Reading runtime activity fabricated mastery/adaptive routing");

            Console.WriteLine("WordDeck governed CE-A1-M08 Reading runtime package self-test PASS.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static IReadOnlyList<string> Channels(StoryCourseModuleContract module, string taskId)
    {
        StoryCourseComprehensionTaskContract task = module.Units
            .SelectMany(unit => unit.ComprehensionTasks)
            .Single(candidate => candidate.TaskId == taskId);
        return module.Objectives.Single(objective => objective.ObjectiveId == task.ObjectiveIds.Single()).EvidenceChannels;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Governed CE-A1-M08 Reading runtime self-test failed: " + message);
    }
}

internal static class StoryCourseRuntimeM08ReadingPackageSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            StoryCourseRuntimeM08ReadingPackageSelfTest.Run();
    }
}
