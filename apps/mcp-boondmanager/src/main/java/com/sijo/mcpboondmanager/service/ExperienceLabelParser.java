package com.sijo.mcpboondmanager.service;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Parses a BoondManager experience dictionary <em>label</em> (e.g. {@code "3 ans"}, {@code "4 ans"},
 * {@code "> à 10 ans"}, {@code "Pas d'expérience"}) into language-neutral numbers.
 *
 * <p>The dictionary ids are non-sequential and tenant-configurable, so the years are derived from the
 * <strong>label text</strong>, never hardcoded against ids. Parsing relies only on digit extraction and a
 * small set of symbolic/textual open-ended markers, which holds across BoondManager's French and English
 * labels.
 */
public final class ExperienceLabelParser {

    private static final Pattern FIRST_INTEGER = Pattern.compile("\\d+");
    private static final String[] OPEN_ENDED_MARKERS = {">", "+", "plus", "more"};

    private ExperienceLabelParser() {
    }

    /**
     * @param label the raw dictionary label (may be {@code null}/blank)
     * @return the parsed lower-bound years and open-ended flag
     */
    public static ParsedLabel parse(String label) {
        if (label == null) {
            return new ParsedLabel(0, false);
        }
        String normalized = label.toLowerCase();

        int minYears = 0;
        Matcher matcher = FIRST_INTEGER.matcher(normalized);
        if (matcher.find()) {
            minYears = Integer.parseInt(matcher.group());
        }

        boolean openEnded = false;
        for (String marker : OPEN_ENDED_MARKERS) {
            if (normalized.contains(marker)) {
                openEnded = true;
                break;
            }
        }

        return new ParsedLabel(minYears, openEnded);
    }

    /**
     * Result of parsing an experience label: the lower-bound number of years and whether the band is
     * open-ended (e.g. {@code "> à 10 ans"}).
     */
    public record ParsedLabel(int minYears, boolean openEnded) {
    }
}
