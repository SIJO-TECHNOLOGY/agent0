package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Attributes of a single candidate as returned by the {@code /candidates} search list.
 *
 * <p>The search payload is flat (there is no nested {@code technicalDocument} object): the skills
 * profile fields ({@code title}, {@code skills}, {@code diplomas}, {@code tools}, …) sit directly
 * on the candidate. Field names follow BoondManager exactly — the contact email is {@code email1},
 * the desired contract type is {@code typeOf}, the city is {@code town} and mobility zones are
 * returned as the {@code mobilityAreas} array. The list endpoint does not expose salary or
 * daily-rate (TJM) expectations.
 *
 * <p>{@code availability} is polymorphic: BoondManager returns the availability-type id as a number
 * for most candidates, but a bare {@code yyyy-MM-dd} date string for candidates flagged "available
 * after date". It is therefore typed as {@link String} (an integer id deserializes to its text
 * form) so both shapes deserialize without error.
 *
 * <p>{@code lastActionDate} is only populated when the {@code lastActionDate} column is requested via
 * the search {@code columns} parameter; otherwise BoondManager omits it and it deserializes to
 * {@code null}. {@code numberOfActivePositionings}, {@code globalEvaluation}, {@code creationDate} and
 * {@code updateDate} are returned by default and are strong ranking signals. {@code references} is the
 * candidate's work history (preserved as nested objects, not flattened); {@code evaluations} is kept
 * raw as it is empty for most candidates and its element shape is account-specific. The list endpoint
 * does not expose salary or daily-rate (TJM) expectations.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondCandidateSummaryAttributes(
        String firstName,
        String lastName,
        String email1,
        String email2,
        String email3,
        String phone1,
        String phone2,
        Integer civility,
        Integer state,
        String availability,
        Integer typeOf,
        List<String> mobilityAreas,
        String town,
        String country,
        String title,
        Integer experience,
        String skills,
        List<String> diplomas,
        List<String> expertiseAreas,
        List<String> activityAreas,
        List<BoondTechnicalDocumentAttributes.Tool> tools,
        List<BoondTechnicalDocumentAttributes.Language> languages,
        String globalEvaluation,
        String creationDate,
        String updateDate,
        String lastActionDate,
        Integer numberOfActivePositionings,
        Integer numberOfResumes,
        BoondSource source,
        List<BoondReference> references,
        List<Object> evaluations,
        List<BoondSocialNetwork> socialNetworks
) {
}
