package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.jspecify.annotations.Nullable;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

@Component
public class CandidateDetailTool {

    private final BoondManagerCandidateService candidateService;

    public CandidateDetailTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "getCandidateDetail",
            description = """
                    Retrieves the detailed information profile of a specific candidate by their \
                    BoondManager ID (GET /candidates/{id}/information).

                    Returns:
                    - Identity: id, firstName, lastName, civility, dateOfBirth, title, initials
                    - Contact: email, email2, email3, phone1, phone2, phone3, fax
                    - Address: address, postCode, city, country, subDivision
                    - Pipeline: state, stateReasonType, stateReasonDetail (why the state was set)
                    - Contract: contractType
                    - Availability: availability (the availability-type id, or a yyyy-MM-dd date \
                    when the candidate is available after a given date)
                    - Mobility: mobilityAreas
                    - Sourcing: sourceType, sourceDetail
                    - Evaluation: globalEvaluation, evaluations (raw, account-specific shape)
                    - Notes: informationComment (free text; gated by includeNotes)
                    - Ownership: mainManagerId, mainManagerName, hrManagerId, hrManagerName, \
                    agencyId, agencyName
                    - Social: socialNetworks (network + url)
                    - Signals: numberOfActivePositionings, creationDate, updateDate, creationSource

                    Not exposed by BoondManager on /candidates/{id}/information: salary, daily-rate \
                    (TJM) expectations, nationality, lastActionDate, and the technical document / \
                    references (use getCandidateTechnicalDocument for those).

                    Call this after searchCandidates to get the full profile of a shortlisted \
                    candidate; the candidateId is the 'id' field from searchCandidates results. Call \
                    order: getDictionary -> searchCandidates -> getCandidateDetail -> \
                    getCandidateTechnicalDocument.""")
    public CandidateDetailDto getCandidateDetail(
            @ToolParam(description =
                    "Unique BoondManager candidate identifier. Obtained from the 'id' field in " +
                    "searchCandidates results.")
            Integer candidateId,
            @ToolParam(required = false, description = """
                    When true, includes the full informationComment free-text notes. \
                    Default: true.""")
            @Nullable Boolean includeNotes
    ) {
        CandidateDetailDto detail = candidateService.getCandidateDetail(candidateId);
        if (Boolean.FALSE.equals(includeNotes)) {
            return withoutNotes(detail);
        }
        return detail;
    }

    /**
     * Returns a copy of the profile with the free-text {@code informationComment} removed. Pure
     * projection — every other field is preserved.
     */
    private static CandidateDetailDto withoutNotes(CandidateDetailDto d) {
        return new CandidateDetailDto(
                d.id(),
                d.firstName(),
                d.lastName(),
                d.email(),
                d.email2(),
                d.email3(),
                d.phone1(),
                d.phone2(),
                d.phone3(),
                d.fax(),
                d.civility(),
                d.dateOfBirth(),
                d.address(),
                d.postCode(),
                d.city(),
                d.country(),
                d.subDivision(),
                d.title(),
                d.initials(),
                d.state(),
                d.stateReasonType(),
                d.stateReasonDetail(),
                d.contractType(),
                d.availability(),
                d.mobilityAreas(),
                d.sourceType(),
                d.sourceDetail(),
                d.globalEvaluation(),
                d.evaluations(),
                d.numberOfActivePositionings(),
                d.socialNetworks(),
                null,                       // informationComment omitted when includeNotes=false
                d.creationDate(),
                d.updateDate(),
                d.creationSource(),
                d.mainManagerId(),
                d.mainManagerName(),
                d.hrManagerId(),
                d.hrManagerName(),
                d.agencyId(),
                d.agencyName()
        );
    }
}