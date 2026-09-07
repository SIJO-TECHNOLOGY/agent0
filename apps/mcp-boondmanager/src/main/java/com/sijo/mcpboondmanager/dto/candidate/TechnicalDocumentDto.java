package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Candidate technical document (BoondManager "dossier technique" / DT).
 *
 * <p>{@code candidateId} is the authoritative id of the candidate ({@code ID_PROFIL}) the document
 * belongs to — it is taken from the request, not from the payload. {@code id}/{@code tdId} identify
 * the <strong>technical document resource itself</strong> ({@code ID_DT}), which BoondManager returns
 * for the candidate's technical-data tab. The candidate id and the technical-data id are
 * <strong>distinct identifiers</strong> and must never be treated as interchangeable.
 *
 * <p>A candidate with no technical document is represented by {@link #notAvailable(Integer)}: only
 * {@code candidateId} is set, every other field is {@code null}/empty/{@code false}.
 *
 * <p>{@code experience} is BoondManager's raw {@code setting.experience} level id (kept for
 * filtering/sorting). The {@code experienceMinYears}/{@code experienceOpenEnded}/
 * {@code experienceSpecified} fields are the language-neutral resolution of that id (years parsed from
 * the dictionary label) so consumers don't need to know BoondManager's dictionary. {@code
 * experienceLabelRaw} is BoondManager's localized label and is <strong>non-authoritative, for debugging
 * only</strong> (not for display or logic).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record TechnicalDocumentDto(
        Integer id,
        String tdId,
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
        Integer candidateId
) {

    /**
     * An empty document for a candidate that has no technical document associated with it.
     * Only {@code candidateId} is populated; everything else is {@code null}/empty/{@code false}.
     */
    public static TechnicalDocumentDto notAvailable(Integer candidateId) {
        return new TechnicalDocumentDto(
                null, null, null, null, null,
                null, null, false, false, null,
                null, null, null, null, null,
                null, null, candidateId);
    }

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
