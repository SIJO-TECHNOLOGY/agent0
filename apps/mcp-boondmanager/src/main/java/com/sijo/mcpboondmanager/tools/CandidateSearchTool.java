package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

@Component
public class CandidateSearchTool {

    private final BoondManagerCandidateService candidateService;

    public CandidateSearchTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "searchCandidates",
            description = "Searches candidates in BoondManager using multiple optional filters. Returns " +
                    "a paginated list of candidate profiles. Use getDictionary first to resolve " +
                    "human-readable values (e.g. 'Bac+5', 'CDI', 'Île-de-France', 'Java') to their " +
                    "BoondManager IDs before calling this tool. The keywords parameter supports " +
                    "full-text search with operators: +term forces inclusion, \"exact phrase\" " +
                    "for exact match. Keywords search covers CV, technical document, name, title, " +
                    "email and phone fields."
    )
    public CandidateSearchResponseDto searchCandidates(
            @ToolParam(required = false, description =
                    "Full-text search. Operators: +term forces inclusion, \"exact phrase\" for " +
                    "exact match. Searches CV, technical document, name, title, email and phone.")
            String keywords,
            @ToolParam(required = false, description =
                    "Candidate pipeline state ID. From getDictionary: setting.state.candidate.")
            Integer state,
            @ToolParam(required = false, description =
                    "Availability type ID. From getDictionary: setting.availability. " +
                    "9 = available after date, -1 = undefined.")
            Integer availabilityType,
            @ToolParam(required = false, description =
                    "ISO 8601 date (yyyy-MM-dd). Used with availabilityType = 9. " +
                    "Candidate available from this date.")
            String availabilityDate,
            @ToolParam(required = false, description =
                    "Desired contract type ID. From getDictionary: setting.typeOf.contract.")
            Integer contractType,
            @ToolParam(required = false, description =
                    "Experience level ID. From getDictionary: setting.experience.")
            Integer experience,
            @ToolParam(required = false, description =
                    "Diploma level ID. From getDictionary: setting.training. Maps to DT_FORMATION field.")
            String training,
            @ToolParam(required = false, description =
                    "Pipe-separated expertise area IDs. From getDictionary: setting.expertiseArea. " +
                    "Example: \"backend|microservices\".")
            String expertiseAreas,
            @ToolParam(required = false, description =
                    "Pipe-separated activity sector IDs. From getDictionary: setting.activityArea. " +
                    "Example: \"finance|industry\".")
            String activityAreas,
            @ToolParam(required = false, description =
                    "Mobility zone option ID. From getDictionary: setting.mobilityArea.")
            String mobilityArea,
            @ToolParam(required = false, description =
                    "Minimum desired salary filter (€/year).")
            Double minSalary,
            @ToolParam(required = false, description =
                    "Maximum desired salary filter (€/year).")
            Double maxSalary,
            @ToolParam(required = false, description =
                    "Minimum desired daily rate filter (€/day).")
            Double minTjm,
            @ToolParam(required = false, description =
                    "Maximum desired daily rate filter (€/day).")
            Double maxTjm,
            @ToolParam(required = false, description =
                    "Page number. Default: 1.")
            Integer page,
            @ToolParam(required = false, description =
                    "Results per page. Default: 25. Max: 100.")
            Integer numberPerPage
    ) {
        CandidateSearchRequestDto request = new CandidateSearchRequestDto(
                keywords,
                state,
                availabilityType,
                availabilityDate,
                contractType,
                experience,
                training,
                expertiseAreas,
                activityAreas,
                mobilityArea,
                minSalary,
                maxSalary,
                minTjm,
                maxTjm,
                page,
                numberPerPage
        );
        return candidateService.searchCandidates(request);
    }
}