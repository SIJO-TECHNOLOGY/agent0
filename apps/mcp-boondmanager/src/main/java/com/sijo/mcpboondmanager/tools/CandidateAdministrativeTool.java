package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.CandidateAdministrativeDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

@Component
public class CandidateAdministrativeTool {

    private final BoondManagerCandidateService candidateService;

    public CandidateAdministrativeTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "getCandidateAdministrative",
            description = "Retrieves the administrative and financial profile of a candidate from " +
                    "BoondManager (GET /candidates/{id}/administrative). Returns salary expectations " +
                    "(currentSalary, minSalary, maxSalary) and daily-rate TJM expectations " +
                    "(currentDailyRate, minDailyRate, maxDailyRate) when set by the recruiter. " +
                    "All values are null when the candidate has not filled them in. " +
                    "Call after searchCandidates when salary or TJM information is needed."
    )
    public CandidateAdministrativeDto getCandidateAdministrative(
            @ToolParam(description =
                    "BoondManager candidate id. Obtained from the 'id' field in searchCandidates results.")
            Integer candidateId
    ) {
        return candidateService.getCandidateAdministrative(candidateId);
    }
}
