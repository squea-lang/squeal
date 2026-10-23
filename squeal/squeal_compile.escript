#!/usr/bin/env escript
%%! -noshell
%% Компиляция Erlang abstract forms squeal (см. architecture.md).
%%
%% usage: squeal_compile.escript JOBS
%%   JOBS — файл с одним Erlang-термом: [{FormsPath, BasePath, Source}, ...]
%%   FormsPath — файл термов (ASCII): одна форма на строку, каждая с точкой
%%   BasePath  — без расширения: MODULE.beam и MODULE.erl лягут рядом
%%   Source    — путь исходника .ee для атрибута -file и debug_info

main([Jobs]) ->
    case file:consult(Jobs) of
        {ok, Jobs_} ->
            compile_jobs(Jobs_);
        {error, Reason} ->
            io:format(standard_error, "read jobs failed: ~p~n", [Reason]),
            halt(1)
    end.

compile_jobs([]) ->
    halt(0);
compile_jobs([{FormsPath, Base, Source} | Rest]) ->
    case file:consult(FormsPath) of
        {ok, Forms} ->
            case compile_one(Forms, Base, Source) of
                ok -> compile_jobs(Rest);
                error -> halt(1)
            end;
        {error, Reason} ->
            io:format(standard_error, "read ~s failed: ~p~n", [FormsPath, Reason]),
            halt(1)
    end.

compile_one(Forms, Base, Source) ->
    Options = [return, report_errors, report_warnings, debug_info, {source, Source}],
    case compile:forms(Forms, Options) of
        {ok, _Mod, Binary} ->
            write(Base, Binary, Forms);
        {ok, _Mod, Binary, _Warnings} ->
            write(Base, Binary, Forms);
        {error, Errors, _Warnings} ->
            %% контракт ошибок (architecture.md): `путь:строка: текст`, без дампа
            io:format(standard_error, "~ts", [format_errors(Source, Errors)]),
            error;
        Other ->
            io:format(standard_error, "~ts: compilation failed~n", [Source]),
            io:format(standard_error, "~P~n", [Other, 8]),
            error
    end.

format_errors(Source, [{_File, Problems} | _]) ->
    [format_problem(Source, P) || P <- Problems];
format_errors(Source, _) ->
    [io_lib:format("~ts: compilation failed~n", [Source])].

format_problem(Source, {Location, Module, Description}) ->
    io_lib:format("~ts:~p: ~ts~n", [Source, line_of(Location), describe(Module, Description)]).

line_of({Line, _Column}) -> Line;
line_of(Line) when is_integer(Line) -> Line;
line_of(_) -> 1.

describe(erl_lint, {undefined_function, {Name, Arity}}) ->
    io_lib:format("function ~ts/~p is not defined", [Name, Arity]);
describe(erl_lint, {undefined_function, {Name, Arity}, Defined}) ->
    io_lib:format("function ~ts/~p is not defined (defined: ~p)", [Name, Arity, Defined]);
describe(erl_lint, {unused_var, Name}) ->
    io_lib:format("variable ~ts is unused", [Name]);
describe(erl_lint, {redefine_type, _}) ->
    "duplicate type definition";
describe(compile, {crash, Module, Kind, _Stack}) ->
    io_lib:format("internal Erlang compiler error (~p:~p) — check the generated forms", [Module, Kind]);
describe(Module, Description) ->
    io_lib:format("~p: ~p", [Module, Description]).

write(Base, Binary, Forms) ->
    ok = file:write_file(Base ++ ".beam", Binary),
    Erl = [erl_pp:form(Form) || Form <- Forms],
    ok = file:write_file(Base ++ ".erl", Erl),
    ok.
