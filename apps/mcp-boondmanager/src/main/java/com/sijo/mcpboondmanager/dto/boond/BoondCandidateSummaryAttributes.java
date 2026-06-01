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
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondCandidateSummaryAttributes(
        String firstName,
        String lastName,
        String email1,
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
        List<BoondTechnicalDocumentAttributes.Language> languages
) {
}
