package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * A single past assignment / work-experience reference as returned by BoondManager under
 * {@code references[]} on both the {@code /candidates} search payload and the
 * {@code /candidates/{id}/technical-data} document.
 *
 * <p>Field names follow BoondManager exactly. The work period is expressed as separate
 * {@code startMonth}/{@code startYear}/{@code endMonth}/{@code endYear} string parts (BoondManager
 * sends them as strings, e.g. {@code "2"}, {@code "2017"}); {@code startDate}/{@code endDate} are the
 * optional ISO forms (often blank). {@code row} is BoondManager's display ordering index. The
 * {@code skills} and {@code description} free-text fields are preserved verbatim — they are a primary
 * matching signal and must never be truncated or aggregated.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondReference(
        String id,
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