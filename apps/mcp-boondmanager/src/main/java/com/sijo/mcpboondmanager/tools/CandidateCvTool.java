package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.CandidateCvDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

@Component
public class CandidateCvTool {

    private final BoondManagerCandidateService candidateService;

    public CandidateCvTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "getCandidateCV",
            description = "Downloads and extracts text from the candidate CV/resume PDF attached " +
                    "to BoondManager. Use after searchCandidates when skills, project history, " +
                    "or experience evidence must be verified from the real CV, not only the " +
                    "technical document."
    )
    public CandidateCvDto getCandidateCV(
            @ToolParam(description =
                    "BoondManager candidate id. Obtained from the 'id' field in searchCandidates results.")
            Integer candidateId
    ) {
        return candidateService.getCandidateCV(candidateId);
    }
}
