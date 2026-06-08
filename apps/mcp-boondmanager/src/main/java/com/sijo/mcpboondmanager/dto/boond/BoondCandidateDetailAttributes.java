package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Attributes returned under {@code data.attributes} by {@code /candidates/{id}/information} — the
 * detailed candidate "information" tab.
 *
 * <p>Field names follow BoondManager exactly: the primary email is {@code email1}, the date of
 * birth is {@code dateOfBirth}, the postal code is {@code postcode}, the city is {@code town}, the
 * desired contract type is {@code typeOf}. The sourcing origin is a nested {@code source} object
 * ({@code typeOf} + {@code detail}) and free-text notes are under {@code informationComments}.
 * The managing resources (mainManager/hrManager) and agency are carried in the JSON:API
 * {@code relationships}/{@code included} sections of the envelope, not under {@code attributes}.
 * Salary/TJM expectations, nationality and {@code lastActionDate} are not exposed by
 * {@code /candidates/{id}/information}.
 *
 * <p>{@code availability} is polymorphic: BoondManager returns the availability-type id as a number
 * for most candidates, but a bare {@code yyyy-MM-dd} date string for candidates flagged "available
 * after date". It is therefore typed as {@link String} so both shapes deserialize without error.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondCandidateDetailAttributes(
        String firstName,
        String lastName,
        String email1,
        String email2,
        String email3,
        String phone1,
        String phone2,
        String phone3,
        String fax,
        Integer civility,
        String dateOfBirth,
        String address,
        String postcode,
        String town,
        String country,
        String subDivision,
        String title,
        String initials,
        Integer state,
        StateReason stateReason,
        Integer typeOf,
        String availability,
        List<String> mobilityAreas,
        Source source,
        String globalEvaluation,
        List<Object> evaluations,
        Integer numberOfActivePositionings,
        List<BoondSocialNetwork> socialNetworks,
        String informationComments,
        String creationDate,
        String updateDate,
        String creationSource
) {

    /**
     * Sourcing origin of the candidate: {@code typeOf} is the source-type id (resolvable through
     * {@code getDictionary: setting.source}) and {@code detail} is the free-text precision.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Source(Integer typeOf, String detail) {
    }

    /**
     * Reason attached to the candidate's pipeline {@code state}: {@code typeOf} is the reason-type id
     * and {@code detail} is the free-text precision.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record StateReason(Integer typeOf, String detail) {
    }
}
