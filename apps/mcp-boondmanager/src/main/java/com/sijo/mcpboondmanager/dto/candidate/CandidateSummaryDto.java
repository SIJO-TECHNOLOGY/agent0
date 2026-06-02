package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Candidate search result summary.
 *
 * <p>{@code experience} is BoondManager's raw {@code setting.experience} level id (kept for
 * filtering/sorting). The {@code experienceMinYears}/{@code experienceOpenEnded}/
 * {@code experienceSpecified} fields are the language-neutral resolution of that id (years parsed from
 * the dictionary label). {@code experienceLabelRaw} is BoondManager's localized label and is
 * <strong>non-authoritative, for debugging only</strong> (not for display or logic).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record CandidateSummaryDto(
        Integer id,
        String firstName,
        String lastName,
        String email,
        Integer state,
        String availability,
        Integer contractType,
        List<String> mobilityAreas,
        String city,
        String country,
        String title,
        Integer experience,
        Integer experienceMinYears,
        boolean experienceOpenEnded,
        boolean experienceSpecified,
        String experienceLabelRaw,
        String skills,
        List<String> diplomas,
        List<String> expertiseAreas,
        List<String> activityAreas,
        List<TechnicalDocumentDto.ToolProficiency> tools,
        List<TechnicalDocumentDto.LanguageProficiency> languages
) {
}
