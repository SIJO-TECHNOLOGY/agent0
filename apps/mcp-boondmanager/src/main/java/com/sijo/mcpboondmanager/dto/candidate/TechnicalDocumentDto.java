package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Candidate technical document (CV / skills profile).
 *
 * <p>{@code id} is the id of the candidate the document belongs to (the endpoint is candidate
 * scoped); {@code tdId} is the technical document's own identifier.
 *
 * <p>{@code experience} is BoondManager's raw {@code setting.experience} level id (kept for
 * filtering/sorting). The {@code experienceMinYears}/{@code experienceOpenEnded}/
 * {@code experienceSpecified} fields are the language-neutral resolution of that id (years parsed from
 * the dictionary label) so consumers don't need to know BoondManager's dictionary. {@code
 * experienceLabelRaw} is BoondManager's localized label and is <strong>non-authoritative, for debugging
 * only</strong> (not for display or logic).
 *
 * <p>{@code references} is the candidate's detailed assignment history (kept as nested
 * {@link ExperienceReference} objects, never flattened); together with {@code skills} it is the richest
 * signal for technical-fit assessment. {@code tdLink} is the optional external document link.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record TechnicalDocumentDto(
        Integer id,
        String tdId,
        String tdLink,
        String title,
        String description,
        String summary,
        Integer experience,
        Integer experienceMinYears,
        boolean experienceOpenEnded,
        boolean experienceSpecified,
        String experienceLabelRaw,
        String training,
        List<String> diplomas,
        String skills,
        List<String> expertiseAreas,
        List<String> activityAreas,
        List<ToolProficiency> tools,
        List<LanguageProficiency> languages,
        List<ExperienceReference> references
) {

    /**
     * A tool/technology mastered by the candidate with its numeric proficiency level.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ToolProficiency(String tool, Integer level) {
    }

    /**
     * A spoken language with its level.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record LanguageProficiency(String language, String level) {
    }
}
