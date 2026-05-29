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
            description = "Retrieves the complete profile of a specific candidate by their BoondManager " +
                    "ID. Returns full contact details, recruitment pipeline state, contract " +
                    "preferences, salary and daily rate expectations, mobility preferences, and " +
                    "recruitment metadata. Call this after searchCandidates to get the full profile " +
                    "of a shortlisted candidate. The candidateId is the 'id' field from " +
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