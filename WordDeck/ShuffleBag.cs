namespace WordDeck;

internal static class ShuffleBag
{
    public static Queue<string> Create(IEnumerable<string> entryIds, Random random, string? avoidFirstId = null)
    {
        List<string> ids = entryIds.ToList();
        for (int i = ids.Count - 1; i > 0; i--)
        {
            int j = random.Next(i + 1);
            (ids[i], ids[j]) = (ids[j], ids[i]);
        }

        if (!string.IsNullOrWhiteSpace(avoidFirstId) && ids.Count > 1 &&
            string.Equals(ids[0], avoidFirstId, StringComparison.OrdinalIgnoreCase))
        {
            int replacement = ids.FindIndex(1, id => !string.Equals(id, avoidFirstId, StringComparison.OrdinalIgnoreCase));
            if (replacement > 0)
                (ids[0], ids[replacement]) = (ids[replacement], ids[0]);
        }

        return new Queue<string>(ids);
    }
}
