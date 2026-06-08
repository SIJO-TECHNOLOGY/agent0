package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * A single past assignment / work-experience reference, as returned on a candidate's technical
 * document and search summary. The free-text {@code skills} and {@code description} are preserved
 * verbatim (never truncated or aggregated) — together with the work period they are a primary signal
 * for technical-fit assessment.
 *
 * <p>The work period is kept as the raw BoondManager {@code startMonth}/{@code startYear}/
 * {@code endMonth}/{@code endYear} string parts plus the optional ISO {@code startDate}/{@code endDate}
 * (often blank). {@code row} is BoondManager's display-ordering index.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record ExperienceReference(
        Integer id,
        String title,
        String company,
        String location,
        String startMonth,
        String startYear,
        String endMonth,
        String endYear,
        String startDate,
        String endDate,
        Integer row,
        String skills,
        String description
) {
}