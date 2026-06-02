package com.sijo.mcpboondmanager.service;

/**
 * Language-neutral, resolved view of a candidate's experience level, derived by looking the raw
 * BoondManager experience id up in the {@code setting.experience} dictionary and parsing its label.
 *
 * @param minYears   lower-bound years of experience ({@code null} when not specified)
 * @param openEnded  {@code true} when the band is open-ended (e.g. {@code "> à 10 ans"})
 * @param specified  {@code false} when the id is {@code -1}, {@code null}, or absent from the dictionary
 * @param rawLabel   BoondManager's localized label — <strong>non-authoritative, for debugging only</strong>
 *                   (do not use for display or logic); {@code null} when not specified
 */
public record ResolvedExperience(
        Integer minYears,
        boolean openEnded,
        boolean specified,
        String rawLabel
) {

    /** Shared instance for {@code -1} / null / unknown ids. */
    public static final ResolvedExperience UNSPECIFIED =
            new ResolvedExperience(null, false, false, null);
}
