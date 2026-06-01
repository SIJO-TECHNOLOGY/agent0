package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.CandidateDetailDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
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
            description = "Retrieves the detailed information profile of a specific candidate by their " +
                    "BoondManager ID. Returns contact details (emails, phones, fax), civility, date of " +
                    "birth, postal address (address, postcode, city, country, subDivision), title and " +
                    "initials, recruitment pipeline state, desired contract type, availability, mobility " +
                    "zones, sourcing origin (sourceType + sourceDetail), global evaluation, free-text " +
                    "information notes, and creation/update metadata. Note: 'availability' is the " +
                    "availability-type id, or a yyyy-MM-dd date when the candidate is available after a " +
                    "given date. BoondManager does not expose salary or daily-rate (TJM) expectations on " +
                    "this endpoint, so they are not returned. Call this after searchCandidates to get the " +
                    "full profile of a shortlisted candidate. The candidateId is the 'id' field from " +
                    "searchCandidates results."
    )
    public CandidateDetailDto getCandidateDetail(
            @ToolParam(description =
                    "Unique BoondManager candidate identifier. Obtained from the 'id' field in " +
                    "searchCandidates results.")
            Integer candidateId
    ) {
        return candidateService.getCandidateDetail(candidateId);
    }
}