package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Candidate search result summary.
 *
 * <p>{@code availability} is a resolved, human-readable {@link String}: the {@code setting.availability}
 * dictionary label for a relative band (e.g. "Immédiate", "3 mois"), the {@code yyyy-MM-dd} date for a
 * candidate available from a specific date, or {@code null} when not specified. The raw BoondManager id
 * is resolved via {@code com.sijo.mcpboondmanager.service.AvailabilityDictionaryResolver}.
 *
 * <p>{@code experience} is BoondManager's raw {@code setting.experience} level id (kept for
 * filtering/sorting). The {@code experienceMinYears}/{@code experienceOpenEnded}/
 * {@code experienceSpecified} fields are the language-neutral resolution of that id (years parsed from
 * the dictionary label). {@code experienceLabelRaw} is BoondManager's localized label and is
 * <strong>non-authoritative, for debugging only</strong> (not for display or logic).
 *
 * <p>{@code availability} is the resolved label while {@code availabilityRaw} keeps BoondManager's raw
 * value (id or date) so no information is lost. {@code numberOfActivePositionings},
 * {@code globalEvaluation}, {@code creationDate}, {@code updateDate} and {@code lastActionDate} are
 * ranking signals; {@code lastActionDate} is only populated when the {@code lastActionDate} column is
 * requested. {@code references} (work history), {@code evaluations} and {@code socialNetworks} are kept
 * as raw nested structures. {@code mainManagerId}/{@code agencyId} keep the relationship ids while
 * {@code mainManagerName}/{@code agencyName} carry the labels resolved from the response's
 * {@code included} section.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record CandidateSummaryDto(
        Integer id,
        String firstName,
        String lastName,
        String email,
        String email2,
        String email3,
        String phone1,
        String phone2,
        Integer civility,
        Integer state,
        String availability,
        String availabilityRaw,
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
        List<TechnicalDocumentDto.LanguageProficiency> languages,
        String globalEvaluation,
        String creationDate,
        String updateDate,
        String lastActionDate,
        Integer numberOfActivePositionings,
        Integer numberOfResumes,
        Integer sourceType,
        String sourceDetail,
        List<ExperienceReference> references,
        List<Object> evaluations,
        List<SocialLink> socialNetworks,
        Integer mainManagerId,
        String mainManagerName,
        Integer agencyId,
        String agencyName
) {
}
