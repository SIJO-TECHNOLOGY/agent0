package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Detailed candidate profile from {@code /candidates/{id}/information}.
 *
 * <p>{@code numberOfActivePositionings} and {@code globalEvaluation} are ranking signals.
 * {@code stateReasonType}/{@code stateReasonDetail} explain the pipeline {@code state}.
 * {@code mainManagerId}/{@code hrManagerId}/{@code agencyId} keep the JSON:API relationship ids while
 * {@code mainManagerName}/{@code hrManagerName}/{@code agencyName} carry the labels resolved from the
 * response's {@code included} section. BoondManager does not expose salary/TJM expectations,
 * nationality or {@code lastActionDate} on this endpoint, so they are not present.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record CandidateDetailDto(
        Integer id,
        String firstName,
        String lastName,
        String email,
        String email2,
        String email3,
        String phone1,
        String phone2,
        String phone3,
        String fax,
        Integer civility,
        String dateOfBirth,
        String address,
        String postCode,
        String city,
        String country,
        String subDivision,
        String title,
        String initials,
        Integer state,
        Integer stateReasonType,
        String stateReasonDetail,
        Integer contractType,
        String availability,
        List<String> mobilityAreas,
        Integer sourceType,
        String sourceDetail,
        String globalEvaluation,
        List<Object> evaluations,
        Integer numberOfActivePositionings,
        List<SocialLink> socialNetworks,
        String informationComment,
        String creationDate,
        String updateDate,
        String creationSource,
        Integer mainManagerId,
        String mainManagerName,
        Integer hrManagerId,
        String hrManagerName,
        Integer agencyId,
        String agencyName
) {
}
