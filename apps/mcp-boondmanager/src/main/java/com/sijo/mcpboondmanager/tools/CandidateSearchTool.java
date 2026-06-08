package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSummaryDto;
import com.sijo.mcpboondmanager.dto.candidate.ExperienceReference;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.jspecify.annotations.Nullable;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
public class CandidateSearchTool {

    private final BoondManagerCandidateService candidateService;

    public CandidateSearchTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "searchCandidates",
            description = """
                    Searches candidates in BoondManager with rich, optional filters and returns a \
                    paginated list of candidate summaries. Use getDictionary first to resolve \
                    human-readable values (states, contract types, mobility zones, expertise areas, \
                    tools, languages, ...) to their BoondManager IDs before calling this tool.

                    Inputs: full-text keyword search with a configurable keywordsType, multi-value \
                    reference filters (repeatable parameters whose values are unioned), geographic \
                    search (location or coordinates together with geoDistance), date-range filtering \
                    (period with startDate/endDate, or periodDynamic), pagination (page, maxResults \
                    up to 500), sorting (sort + order) and response field selection (columns).

                    Returns a list of candidate summaries, each with:
                    - Identity: id, firstName, lastName, civility, title
                    - Contact: email, email2, email3, phone1, phone2
                    - Location: city, country, mobilityAreas
                    - Pipeline: state
                    - Availability: availability (resolved label or yyyy-MM-dd date), \
                    availabilityRaw (raw BoondManager id or date)
                    - Contract: contractType
                    - Experience: experience (raw level id), experienceMinYears, \
                    experienceOpenEnded, experienceSpecified (language-neutral resolution), \
                    experienceLabelRaw (localized label, debug only)
                    - Skills profile: skills (resume/skills free text), diplomas, expertiseAreas, \
                    activityAreas, tools (with proficiency level), languages (with level)
                    - Work history: references (per-assignment title, company, location, work \
                    period, and free-text skills/description — the richest matching signal)
                    - Evaluation: globalEvaluation, evaluations (raw, account-specific shape)
                    - Sourcing: sourceType, sourceDetail
                    - Ownership: mainManagerId, mainManagerName, agencyId, agencyName
                    - Signals: numberOfActivePositionings, numberOfResumes, creationDate, \
                    updateDate, lastActionDate (only when the lastActionDate column is requested)
                    - Social: socialNetworks (network + url)

                    Set includeResume=true to also receive the skills free text and the \
                    references[].skills / references[].description free text in each result; by \
                    default they are omitted to keep large result sets lightweight.

                    Not exposed by BoondManager on the /candidates list endpoint: salary, \
                    daily-rate (TJM) expectations, nationality.

                    Call getCandidateDetail for a full profile and getCandidateTechnicalDocument \
                    for the deep skills/CV or if a value is missing. Call order: getDictionary -> searchCandidates -> \
                    getCandidateDetail -> getCandidateTechnicalDocument.""")
    public CandidateSearchResponseDto searchCandidates(
            @ToolParam(required = false, description =
                    "Full-text search query. Operators: +term forces inclusion, \"exact phrase\" for " +
                    "exact match. The field(s) searched are controlled by keywordsType.")
            String keywords,
            @ToolParam(required = false, description =
                    "Which field the keywords search targets. One of: resumeTd (default; resume + " +
                    "technical document), lastName, firstName, fullName, strictFullName, emails, " +
                    "title, titleSkills, phones, resume, td.")
            String keywordsType,
            @ToolParam(required = false, description =
                    "Candidate pipeline state IDs (repeatable; values are unioned). " +
                    "From getDictionary: setting.state.candidate." +
                    "By default 0 ('Import à traiter') is excluded to avoid null values on other field.")
            List<Integer> candidateStates,
            @ToolParam(required = false, description =
                    "Candidate type IDs (repeatable). From getDictionary: setting.typeOf.resource.")
            List<Integer> candidateTypes,
            @ToolParam(required = false, description =
                    "Availability type IDs (repeatable). From getDictionary: setting.availability.")
            List<Integer> availabilityTypes,
            @ToolParam(required = false, description =
                    "Desired contract type IDs (repeatable). From getDictionary: setting.typeOf.contract.")
            List<Integer> contractTypes,
            @ToolParam(required = false, description =
                    "Experience level IDs (repeatable). From getDictionary: setting.experience.")
            List<Integer> experiences,
            @ToolParam(required = false, description =
                    "Expertise area IDs (repeatable). From getDictionary: setting.expertiseArea.")
            List<String> expertiseAreas,
            @ToolParam(required = false, description =
                    "Activity sector IDs (repeatable). From getDictionary: the nested option IDs under " +
                    "setting.activityArea[].option (the top-level setting.activityArea entries are " +
                    "group headings, not selectable IDs).")
            List<String> activityAreas,
            @ToolParam(required = false, description =
                    "Mobility zone ID. From getDictionary: the nested option IDs under " +
                    "setting.mobilityArea[].option (the top-level entries are group headings).")
            String mobilityAreas,
            @ToolParam(required = false, description =
                    "Spoken-language filters (repeatable), each formatted \"<spokenId>|<levelId>\". " +
                    "From getDictionary: setting.languageSpoken (spokenId) and setting.languageLevel " +
                    "(levelId). Example: \"anglais|courant\".")
            List<String> languages,
            @ToolParam(required = false, description =
                    "Tool/technology IDs (repeatable). From getDictionary: setting.tool. Add the " +
                    "literal \"#AND#\" as the FIRST element to require ALL listed tools; otherwise " +
                    "ANY of them matches.")
            List<String> tools,
            @ToolParam(required = false, description =
                    "Evaluation score IDs (repeatable). From getDictionary: setting.evaluation.")
            List<String> evaluations,
            @ToolParam(required = false, description =
                    "Sourcing origin IDs (repeatable). From getDictionary: setting.source.")
            List<String> sources,
            @ToolParam(required = false, description =
                    "Profile completeness filter (repeatable). One or more of: uncomplete, minimum, " +
                    "complete.")
            List<String> shields,
            @ToolParam(required = false, description =
                    "Free-text address to geocode for a geographic search (e.g. \"Paris\"). " +
                    "Requires geoDistance.")
            String location,
            @ToolParam(required = false, description =
                    "Geographic point as \"latitude,longitude\" (e.g. \"48.8566,2.3522\"). " +
                    "Requires geoDistance. Alternative to location.")
            String coordinates,
            @ToolParam(required = false, description =
                    "Search radius in kilometers (5-200). Required when using location or coordinates.")
            Integer geoDistance,
            @ToolParam(required = false, description =
                    "Date field to filter on, used together with startDate/endDate. One of: created, " +
                    "available, updated, noAction, withActions.")
            String period,
            @ToolParam(required = false, description =
                    "Start of the period range, ISO date yyyy-MM-dd. Used with period.")
            String startDate,
            @ToolParam(required = false, description =
                    "End of the period range, ISO date yyyy-MM-dd. Used with period.")
            String endDate,
            @ToolParam(required = false, description =
                    "Relative period preset instead of startDate/endDate. Examples: thisMonth, " +
                    "lastMonth, nextMonth, thisYear.")
            String periodDynamic,
            @ToolParam(required = false, description =
                    "Page number (1-based). Default: 1.")
            Integer page,
            @ToolParam(required = false, description =
                    "Results per page (1-500). Default: 30.")
            Integer maxResults,
            @ToolParam(required = false, description =
                    "Sort field(s), repeatable. One or more of: lastName, firstName, title, " +
                    "availability, availabilityType, numberOfActivePositionings, mainManager.lastName, " +
                    "updateDate, state, experience, creationDate, evaluation, hrManager.lastName, " +
                    "source, distance.")
            List<String> sort,
            @ToolParam(required = false, description =
                    "Sort direction: asc or desc.")
            String order,
            @ToolParam(required = false, description =
                    "Which fields the API should include in each candidate of the response " +
                    "(repeatable). One or more of: name, title, state, activePositionings, " +
                    "availability, mobilityAreas, details, updated, mainManager, resume, hrManager, " +
                    "expertiseAreas, creationDate, lastActionDate, source, diplomas, activityAreas, " +
                    "globalEvaluation, evaluations, experience, references, languages, tools.")
            List<String> columns,
            @ToolParam(required = false, description = """
                    When true, includes the resume/skills free text in each candidate result: the \
                    top-level skills field and the references[].skills / references[].description \
                    free text. Useful for deep keyword matching. Default: false (lighter response \
                    for large result sets — those free-text fields are omitted while reference \
                    titles, companies and dates are kept).""")
            @Nullable Boolean includeResume
    ) {
        CandidateSearchRequestDto request = new CandidateSearchRequestDto(
                keywords,
                keywordsType,
                candidateStates,
                candidateTypes,
                availabilityTypes,
                contractTypes,
                experiences,
                expertiseAreas,
                activityAreas,
                mobilityAreas,
                languages,
                tools,
                evaluations,
                sources,
                shields,
                location,
                coordinates,
                geoDistance,
                period,
                startDate,
                endDate,
                periodDynamic,
                page,
                maxResults,
                sort,
                order,
                columns
        );
        CandidateSearchResponseDto response = candidateService.searchCandidates(request);
        if (Boolean.TRUE.equals(includeResume)) {
            return response;
        }
        return stripResume(response);
    }

    /**
     * Returns a copy of the response with the resume/skills free text removed from every candidate
     * (the {@code skills} field and the {@code skills}/{@code description} of each work reference).
     * Pure projection — no field is dropped beyond the free text gated by {@code includeResume}.
     */
    private static CandidateSearchResponseDto stripResume(CandidateSearchResponseDto response) {
        if (response.candidates() == null) {
            return response;
        }
        List<CandidateSummaryDto> stripped = response.candidates().stream()
                .map(CandidateSearchTool::stripResume)
                .toList();
        return new CandidateSearchResponseDto(stripped, response.meta());
    }

    private static CandidateSummaryDto stripResume(CandidateSummaryDto c) {
        return new CandidateSummaryDto(
                c.id(),
                c.firstName(),
                c.lastName(),
                c.email(),
                c.email2(),
                c.email3(),
                c.phone1(),
                c.phone2(),
                c.civility(),
                c.state(),
                c.availability(),
                c.availabilityRaw(),
                c.contractType(),
                c.mobilityAreas(),
                c.city(),
                c.country(),
                c.title(),
                c.experience(),
                c.experienceMinYears(),
                c.experienceOpenEnded(),
                c.experienceSpecified(),
                c.experienceLabelRaw(),
                null,                          // skills free text omitted unless includeResume=true
                c.diplomas(),
                c.expertiseAreas(),
                c.activityAreas(),
                c.tools(),
                c.languages(),
                c.globalEvaluation(),
                c.creationDate(),
                c.updateDate(),
                c.lastActionDate(),
                c.numberOfActivePositionings(),
                c.numberOfResumes(),
                c.sourceType(),
                c.sourceDetail(),
                stripResume(c.references()),   // reference free text omitted; titles/dates kept
                c.evaluations(),
                c.socialNetworks(),
                c.mainManagerId(),
                c.mainManagerName(),
                c.agencyId(),
                c.agencyName()
        );
    }

    private static List<ExperienceReference> stripResume(List<ExperienceReference> references) {
        if (references == null) {
            return null;
        }
        return references.stream()
                .map(r -> new ExperienceReference(
                        r.id(),
                        r.title(),
                        r.company(),
                        r.location(),
                        r.startMonth(),
                        r.startYear(),
                        r.endMonth(),
                        r.endYear(),
                        r.startDate(),
                        r.endDate(),
                        r.row(),
                        null,   // skills free text omitted unless includeResume=true
                        null))  // description free text omitted unless includeResume=true
                .toList();
    }
}
