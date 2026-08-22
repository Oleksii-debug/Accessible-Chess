namespace WordDeck;

internal sealed class ShortcutManager
{
    private readonly AppState _state;
    private readonly ShortcutDispatchContext _dispatchContext;
    private List<DeckDefinition> _spellingDecks;
    private bool _hasSpellingDeckContext;
    private static IReadOnlyList<ShortcutDefinition> RecallDefinitions { get; } = BuildRecallDefinitions();
    private static IReadOnlyList<ShortcutDefinition> ScopeDefinitions { get; } = BuildScopeDefinitions();
    private static IReadOnlyList<ShortcutDefinition> SpellingDefinitions { get; } = BuildSpellingDefinitions();
    private static IReadOnlyList<ShortcutDefinition> SentenceDefinitions { get; } = BuildSentenceDefinitions();

    public IReadOnlyList<ShortcutDefinition> Definitions { get; private set; }
    public IReadOnlyList<ShortcutDefinition> CurrentDefinitions => Definitions;

    // MainForm historically constructs the manager with AppState only. Keep
    // that single-argument surface explicitly Recall-scoped so fixed Spelling
    // and Sentence definitions remain visible for F1/conflict truth without
    // swallowing their menu entry-point shortcuts in MainForm.ProcessCmdKey.
    public ShortcutManager(AppState state)
        : this(state, null, ShortcutDispatchContext.Recall)
    {
    }

    // Callers that provide training deck context retain the canonical default
    // All behavior used by training settings and existing regression tests.
    public ShortcutManager(AppState state, IEnumerable<DeckDefinition>? spellingDecks, ShortcutDispatchContext dispatchContext = ShortcutDispatchContext.All)
    {
        _state = AppStateStore.Normalize(state);
        _dispatchContext = dispatchContext;
        _hasSpellingDeckContext = spellingDecks is not null;
        _spellingDecks = spellingDecks?.ToList() ?? new List<DeckDefinition>();
        Definitions = BuildDefinitions();
        EnsureDefaults();
    }

    public void RefreshDeckDefinitions(IEnumerable<DeckDefinition>? spellingDecks = null)
    {
        if (spellingDecks is not null)
        {
            _hasSpellingDeckContext = true;
            _spellingDecks = spellingDecks.ToList();
        }
        Definitions = BuildDefinitions();
        EnsureDefaults();
        RemoveOrphanedDeckShortcuts();
    }

    public Keys Get(string actionId)
    {
        ShortcutDefinition? definition = Definitions.FirstOrDefault(x => x.Id == actionId);
        if (definition is null) return Keys.None;
        Keys candidate = GetCandidateKey(definition);
        if (candidate == Keys.None) return Keys.None;
        return FindConflictingActionId(actionId, candidate) is null ? candidate : Keys.None;
    }

    public string? FindAction(Keys keyData)
    {
        if (keyData == Keys.None) return null;
        ShortcutDefinition? definition = Definitions.FirstOrDefault(def =>
            ShortcutDispatchPolicy.ActionMatchesContext(def.Id, _dispatchContext) &&
            Get(def.Id) != Keys.None && Get(def.Id) == keyData);
        return definition?.Id;
    }

    public bool TrySet(string actionId, Keys keys, out string? errorDescription)
    {
        if (!Definitions.Any(def => def.Id == actionId))
        {
            errorDescription = "the function no longer exists";
            return false;
        }
        if (keys != Keys.None && IsUnsafe(actionId, keys))
        {
            errorDescription = "this combination is reserved for Windows or standard keyboard navigation";
            return false;
        }

        string? conflictId = keys == Keys.None ? null : FindConflictingActionId(actionId, keys);
        if (conflictId is not null)
        {
            string description = Definitions.FirstOrDefault(def =>
                string.Equals(def.Id, conflictId, StringComparison.OrdinalIgnoreCase))?.Description ?? conflictId;
            errorDescription = $"it is already assigned to {description}";
            return false;
        }

        _state.Shortcuts[actionId] = keys.ToString();
        errorDescription = null;
        return true;
    }

    public void Clear(string actionId)
    {
        if (Definitions.Any(def => def.Id == actionId)) _state.Shortcuts[actionId] = Keys.None.ToString();
    }

    public void ResetDefaults()
    {
        foreach (ShortcutDefinition def in Definitions) _state.Shortcuts[def.Id] = def.DefaultKeys.ToString();
    }

    private void EnsureDefaults()
    {
        foreach (ShortcutDefinition def in Definitions) _state.Shortcuts.TryAdd(def.Id, def.DefaultKeys.ToString());
    }

    private Keys GetCandidateKey(ShortcutDefinition definition)
    {
        if (_state.Shortcuts.TryGetValue(definition.Id, out string? raw) && Enum.TryParse(raw, out Keys keys))
        {
            if (keys == Keys.None) return Keys.None;
            if (!IsUnsafe(definition.Id, keys)) return keys;
        }
        return definition.DefaultKeys;
    }

    private string? FindConflictingActionId(string actionId, Keys keys)
    {
        // Check the persisted registry, not only the definitions visible in the
        // current window. This prevents a Recall-only settings surface from
        // assigning a key already owned by a dynamic Spelling deck action.
        // Legacy numeric Recall deck aliases are intentionally ignored: state
        // migration copies them to durable IDs but keeps the old keys for safe
        // backward compatibility, so the alias is not a second live command.
        foreach ((string otherActionId, string raw) in _state.Shortcuts)
        {
            if (string.Equals(otherActionId, actionId, StringComparison.OrdinalIgnoreCase)) continue;
            if (IsLegacyNumericDeckAction(otherActionId)) continue;
            if (!Enum.TryParse(raw, out Keys otherKeys) || otherKeys == Keys.None) continue;
            if (otherKeys == keys) return otherActionId;
        }
        return null;
    }

    private void RemoveOrphanedDeckShortcuts()
    {
        var valid = new HashSet<string>(Definitions.Select(def => def.Id), StringComparer.OrdinalIgnoreCase);
        foreach (string actionId in _state.Shortcuts.Keys.Where(IsDynamicDeckAction).Where(id => !valid.Contains(id) && !IsLegacyNumericDeckAction(id)).ToList())
        {
            // Recall-only refreshes do not know the live Spelling deck topology.
            // Preserve those bindings until a manager with explicit Spelling
            // deck context can prove that a dynamic action is genuinely orphaned.
            if (!_hasSpellingDeckContext && IsSpellingDynamicDeckAction(actionId)) continue;
            _state.Shortcuts.Remove(actionId);
        }
    }

    private static bool IsDynamicDeckAction(string id) =>
        id.StartsWith("switch_deck_", StringComparison.OrdinalIgnoreCase) || id.StartsWith("move_to_deck_", StringComparison.OrdinalIgnoreCase) ||
        IsSpellingDynamicDeckAction(id);

    private static bool IsSpellingDynamicDeckAction(string id) =>
        id.StartsWith("spelling_switch_deck_", StringComparison.OrdinalIgnoreCase) ||
        id.StartsWith("spelling_move_to_deck_", StringComparison.OrdinalIgnoreCase);

    private static bool IsLegacyNumericDeckAction(string id)
    {
        string prefix = id.StartsWith("switch_deck_", StringComparison.OrdinalIgnoreCase) ? "switch_deck_" :
            id.StartsWith("move_to_deck_", StringComparison.OrdinalIgnoreCase) ? "move_to_deck_" : string.Empty;
        return prefix.Length > 0 && int.TryParse(id[prefix.Length..], out int number) && number is >= 1 and <= 5;
    }

    private static bool IsUnsafe(string actionId, Keys keys)
    {
        Keys code = keys & Keys.KeyCode; Keys modifiers = keys & Keys.Modifiers;
        if (code is Keys.None or Keys.Tab or Keys.Escape or Keys.Enter) return true;
        if (code == Keys.F4 && modifiers == Keys.Alt) return true;
        if (code == Keys.Delete && modifiers == (Keys.Control | Keys.Alt)) return true;
        if (modifiers == Keys.None)
        {
            if (code == Keys.Down) return actionId != ActionIds.NextWord;
            if (code == Keys.Up) return actionId != ActionIds.PreviousWord;
            if (code is Keys.Left or Keys.Right or Keys.Home or Keys.End or Keys.PageUp or Keys.PageDown) return true;
        }
        return false;
    }

    private static IReadOnlyList<ShortcutDefinition> BuildRecallDefinitions() => new List<ShortcutDefinition>
    {
        new(ActionIds.NextWord, "Recall: next word", Keys.Down),
        new(ActionIds.PreviousWord, "Recall: previous actually shown word", Keys.Up),
        new(ActionIds.RevealTranslation, "Reveal translation", Keys.Control | Keys.T),
        new(ActionIds.RepeatWord, "Repeat current English word with screen reader", Keys.Control | Keys.R),
        new(ActionIds.PlayPronunciation, "Play generated British pronunciation", Keys.Control | Keys.P),
        new(ActionIds.ToggleAutoPronunciation, "Toggle automatic British pronunciation", Keys.Control | Keys.Shift | Keys.P),
        new(ActionIds.AddWords, "Add pasted word pairs to active deck", Keys.Control | Keys.Shift | Keys.A),
        new(ActionIds.SaveProgress, "Save progress now", Keys.Control | Keys.S),
        new(ActionIds.UndoMove, "Undo last deck move", Keys.Control | Keys.Z),
        new(ActionIds.HideCurrentWord, "Hide current word from Recall study", Keys.Control | Keys.Delete),
        new(ActionIds.RestoreHiddenWords, "Restore a hidden Recall word", Keys.Control | Keys.Alt | Keys.U),
        new(ActionIds.RestoreAllHiddenWords, "Restore all hidden Recall words", Keys.None),
        new(ActionIds.ExportProfile, "Export personal progress profile", Keys.Control | Keys.Alt | Keys.E),
        new(ActionIds.ImportProfile, "Import personal progress profile", Keys.Control | Keys.Shift | Keys.I),
        new(ActionIds.ResetLearningData, "Reset Recall learning data after backup", Keys.None),
        new(ActionIds.ShortcutSettings, "Open shortcut settings", Keys.Control | Keys.K),
        new(ActionIds.Help, "Open help", Keys.F1),
    };

    private static IReadOnlyList<ShortcutDefinition> BuildScopeDefinitions() =>
        StudyScopeIds.Ordered.Select(scopeId => new ShortcutDefinition(
            ActionIds.SwitchStudyScope(scopeId),
            $"Recall: switch study scope to {StudyScopeIds.DisplayName(scopeId)}",
            Keys.None)).ToList();

    private static IReadOnlyList<ShortcutDefinition> BuildSpellingDefinitions() => new List<ShortcutDefinition>
    {
        new(ActionIds.OpenSpelling, "Open Spelling trainer", Keys.Control | Keys.Shift | Keys.S),
        new(ActionIds.SpellingShowAnswer, "Spelling: show required English answer", Keys.Control | Keys.Shift | Keys.H),
        new(ActionIds.SpellingRepeatPrompt, "Spelling: repeat Ukrainian prompt", Keys.Control | Keys.Shift | Keys.R),
        new(ActionIds.SpellingPlayPronunciation, "Spelling: play British pronunciation hint", Keys.Control | Keys.Shift | Keys.B),
        new(ActionIds.SpellingToggleCoach, "Spelling: toggle adaptive coach", Keys.Control | Keys.Alt | Keys.C),
        new(ActionIds.SpellingUndoCoachMove, "Spelling: undo last adaptive move", Keys.Control | Keys.Alt | Keys.Z),
        new(ActionIds.SpellingMoveChooser, "Spelling: move current word to deck chooser", Keys.Control | Keys.Alt | Keys.M),
        new(ActionIds.SpellingCreateDeck, "Spelling: create deck", Keys.Control | Keys.Alt | Keys.N),
        new(ActionIds.SpellingRenameDeck, "Spelling: rename active deck", Keys.Control | Keys.Alt | Keys.R),
        new(ActionIds.SpellingDeleteDeck, "Spelling: delete active user deck", Keys.Control | Keys.Shift | Keys.Delete),
        new(ActionIds.SpellingMoveDeckUp, "Spelling: move active deck up", Keys.Control | Keys.Alt | Keys.Up),
        new(ActionIds.SpellingMoveDeckDown, "Spelling: move active deck down", Keys.Control | Keys.Alt | Keys.Down),
    };

    private static IReadOnlyList<ShortcutDefinition> BuildSentenceDefinitions() => new List<ShortcutDefinition>
    {
        new(ActionIds.OpenSentenceCoach, "Open Sentence Spelling trainer", Keys.Control | Keys.Shift | Keys.E),
        new(ActionIds.SentenceShowAnswer, "Sentence Spelling: show required English answer", Keys.Control | Keys.Alt | Keys.H),
        new(ActionIds.SentenceRepeatPrompt, "Sentence Spelling: repeat Ukrainian sentence", Keys.Control | Keys.Alt | Keys.P),
        new(ActionIds.SentenceImportPack, "Sentence Spelling: import SentencePack", Keys.Control | Keys.Alt | Keys.I),
    };

    private IReadOnlyList<ShortcutDefinition> BuildDefinitions()
    {
        var defs = new List<ShortcutDefinition>(RecallDefinitions);
        defs.AddRange(ScopeDefinitions);
        defs.AddRange(SpellingDefinitions);
        defs.AddRange(SentenceDefinitions);

        foreach (DeckDefinition deck in _state.Decks.OrderBy(deck => deck.Order))
        {
            int coreNumber = DeckIds.CoreDecks.ToList().FindIndex(id => string.Equals(id, deck.Id, StringComparison.OrdinalIgnoreCase)) + 1;
            Keys switchDefault = coreNumber is >= 1 and <= 5 ? Keys.Control | (Keys)((int)Keys.D0 + coreNumber) : Keys.None;
            Keys moveDefault = coreNumber is >= 1 and <= 5 ? Keys.Alt | (Keys)((int)Keys.D0 + coreNumber) : Keys.None;
            defs.Add(new(ActionIds.SwitchDeck(deck.Id), $"Switch to deck: {deck.Name}", switchDefault));
            defs.Add(new(ActionIds.MoveToDeck(deck.Id), $"Move current word to deck: {deck.Name}", moveDefault));
        }

        if (_hasSpellingDeckContext)
        {
            foreach (DeckDefinition deck in _spellingDecks.OrderBy(deck => deck.Order))
            {
                int coreNumber = SpellingDeckIds.CoreDecks.ToList().FindIndex(id => string.Equals(id, deck.Id, StringComparison.OrdinalIgnoreCase)) + 1;
                Keys switchDefault = coreNumber is >= 1 and <= 5 ? Keys.Control | Keys.Shift | (Keys)((int)Keys.D0 + coreNumber) : Keys.None;
                Keys moveDefault = coreNumber is >= 1 and <= 5 ? Keys.Alt | Keys.Shift | (Keys)((int)Keys.D0 + coreNumber) : Keys.None;
                defs.Add(new(ActionIds.SpellingSwitchDeck(deck.Id), $"Spelling: switch to deck: {deck.Name}", switchDefault));
                defs.Add(new(ActionIds.SpellingMoveToDeck(deck.Id), $"Spelling: move current word to deck: {deck.Name}", moveDefault));
            }
        }
        return defs;
    }
}
