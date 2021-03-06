# coding=utf-8

from itertools import chain

from flask import render_template, request, redirect, url_for, abort, session, Markup, make_response
from flask_login import current_user, current_app
import six

from dmapiclient import APIError
from dmapiclient.audit import AuditTypes
from dmutils.email import send_email, generate_token, EmailError
from dmutils.forms import render_template_with_csrf
from dmcontent.content_loader import ContentNotFoundError

from ...main import main, content_loader
from ... import data_api_client
from ..forms.suppliers import (
    EditSupplierForm, EditContactInformationForm, DunsNumberForm, CompaniesHouseNumberForm,
    CompanyContactDetailsForm, CompanyNameForm, EmailAddressForm
)
from app.main.helpers.users import generate_supplier_invitation_token
from ..helpers.frameworks import get_frameworks_by_status
from ..helpers import debug_only, hash_email, login_required
from .users import get_current_suppliers_users


@main.route('')
@login_required
def dashboard():
    supplier = data_api_client.get_supplier(
        current_user.supplier_code
    )['supplier']
    supplier['contact'] = supplier['contacts'][0]

    all_frameworks = sorted(
        data_api_client.find_frameworks()['frameworks'],
        key=lambda framework: framework['slug'],
        reverse=True
    )
    supplier_frameworks = {
        framework['frameworkSlug']: framework
        for framework in data_api_client.get_supplier_frameworks(current_user.supplier_code)['frameworkInterest']
    }

    for framework in all_frameworks:
        framework.update(
            supplier_frameworks.get(framework['slug'], {})
        )
        dates = {}
        try:
            dates = content_loader.get_message(framework['slug'], 'dates')
        except ContentNotFoundError:
            pass
        framework.update({
            'dates': dates,
            'deadline': Markup("Deadline: {}".format(dates.get('framework_close_date', ''))),
            'registered_interest': (framework['slug'] in supplier_frameworks),
            'made_application': (
                framework.get('declaration') and
                framework['declaration'].get('status') == 'complete' and
                framework.get('complete_drafts_count') > 0
            ),
            'needs_to_complete_declaration': (
                framework.get('onFramework') and
                framework.get('agreementReturned') is False
            )
        })

    return render_template_with_csrf(
        "suppliers/dashboard.html",
        supplier=supplier,
        users=get_current_suppliers_users(),
        frameworks={
            'coming': get_frameworks_by_status(all_frameworks, 'coming'),
            'open': get_frameworks_by_status(all_frameworks, 'open'),
            'pending': get_frameworks_by_status(all_frameworks, 'pending'),
            'standstill': get_frameworks_by_status(all_frameworks, 'standstill', 'made_application'),
            'live': get_frameworks_by_status(all_frameworks, 'live', 'services_count')
        }
    )


@main.route('/edit', methods=['GET'])
@debug_only
@login_required
def edit_supplier(supplier_form=None, contact_form=None, error=None):
    try:
        supplier = data_api_client.get_supplier(
            current_user.supplier_code
        )['supplier']
    except APIError as e:
        abort(e.status_code)

    if supplier_form is None:
        supplier_form = EditSupplierForm(
            description=supplier.get('description', None),
            clients=supplier.get('clients', None)
        )
        contact_form = EditContactInformationForm(
            prefix='contact_',
            **supplier['contacts'][0]
        )

    return render_template_with_csrf(
        "suppliers/edit_supplier.html",
        error=error,
        supplier_form=supplier_form,
        contact_form=contact_form
    )


@main.route('/edit', methods=['POST'])
@debug_only
@login_required
def update_supplier():
    # FieldList expects post parameter keys to have number suffixes
    # (eg client-0, client-1 ...), which is incompatible with how
    # JS list-entry plugin generates input names. So instead of letting
    # the form search for request keys we pass in the values directly as data
    supplier_form = EditSupplierForm(
        csrf_token=request.form['csrf_token'],
        description=request.form['description'],
        clients=filter(None, request.form.getlist('clients'))
    )

    contact_form = EditContactInformationForm(request.form, prefix='contact_')
    contact_form.csrf_token.data = request.form['csrf_token']

    if not (supplier_form.validate() and contact_form.validate()):
        response = make_response(edit_supplier(supplier_form=supplier_form, contact_form=contact_form))
        response.status_code = 400
        return response

    # This form data is passed as-is to the API backend.  We don't need to send the CSRF token.
    del supplier_form.csrf_token
    del contact_form.csrf_token

    try:
        data_api_client.update_supplier(
            current_user.supplier_code,
            supplier_form.data,
            current_user.email_address
        )

        data_api_client.update_contact_information(
            current_user.supplier_code,
            contact_form.id.data,
            contact_form.data,
            current_user.email_address
        )
    except APIError as e:
        response = make_response(edit_supplier(supplier_form=supplier_form,
                                               contact_form=contact_form,
                                               error=e.message))
        response.status_code = 500
        return response

    return redirect(url_for(".dashboard"))


@main.route('/create', methods=['GET'])
@debug_only
def create_new_supplier():
    return render_template_with_csrf(
        "suppliers/create_new_supplier.html"
    )


@main.route('/companies-house-number', methods=['GET'])
@debug_only
def companies_house_number():
    form = CompaniesHouseNumberForm()

    if form.companies_house_number.name in session:
        form.companies_house_number.data = session[form.companies_house_number.name]

    return render_template_with_csrf(
        "suppliers/companies_house_number.html",
        form=form
    )


@main.route('/companies-house-number', methods=['POST'])
@debug_only
def submit_companies_house_number():
    form = CompaniesHouseNumberForm(request.form)

    if form.validate():
        if form.companies_house_number.data:
            session[form.companies_house_number.name] = form.companies_house_number.data
        else:
            session.pop(form.companies_house_number.name, None)
        return redirect(url_for(".company_name"))
    else:
        current_app.logger.warning(
            "suppliercreate.fail: duns:{duns} {duns_errors}",
            extra={
                'duns': session.get('duns_number'),
                'duns_errors': ",".join(chain.from_iterable(form.errors.values()))})
        return render_template_with_csrf(
            "suppliers/companies_house_number.html",
            status_code=400,
            form=form
        )


@main.route('/company-name', methods=['GET'])
@debug_only
def company_name():
    form = CompanyNameForm()

    if form.company_name.name in session:
        form.company_name.data = session[form.company_name.name]

    return render_template_with_csrf(
        "suppliers/company_name.html",
        form=form
    )


@main.route('/company-name', methods=['POST'])
@debug_only
def submit_company_name():
    form = CompanyNameForm(request.form)

    if form.validate():
        session[form.company_name.name] = form.company_name.data
        return redirect(url_for(".company_contact_details"))
    else:
        current_app.logger.warning(
            "suppliercreate.fail: duns:{duns} company_name:{company_name} {duns_errors}",
            extra={
                'duns': session.get('duns_number'),
                'company_name': session.get('company_name'),
                'duns_errors': ",".join(chain.from_iterable(form.errors.values()))})
        return render_template_with_csrf(
            "suppliers/company_name.html",
            status_code=400,
            form=form
        )


@main.route('/company-contact-details', methods=['GET'])
@debug_only
def company_contact_details():
    form = CompanyContactDetailsForm()

    if form.email_address.name in session:
        form.email_address.data = session[form.email_address.name]

    if form.phone_number.name in session:
        form.phone_number.data = session[form.phone_number.name]

    if form.contact_name.name in session:
        form.contact_name.data = session[form.contact_name.name]

    return render_template_with_csrf(
        "suppliers/company_contact_details.html",
        form=form
    )


@main.route('/company-contact-details', methods=['POST'])
@debug_only
def submit_company_contact_details():
    form = CompanyContactDetailsForm(request.form)

    if form.validate():
        session[form.email_address.name] = form.email_address.data
        session[form.phone_number.name] = form.phone_number.data
        session[form.contact_name.name] = form.contact_name.data
        return redirect(url_for(".create_your_account"))
    else:
        current_app.logger.warning(
            "suppliercreate.fail: duns:{duns} company_name:{company_name} {duns_errors}",
            extra={
                'duns': session.get('duns_number'),
                'company_name': session.get('company_name'),
                'duns_errors': ",".join(chain.from_iterable(form.errors.values()))})
        return render_template_with_csrf(
            "suppliers/company_contact_details.html",
            status_code=400,
            form=form
        )


@main.route('/create-your-account', methods=['GET'])
@debug_only
def create_your_account():
    current_app.logger.info(
        "suppliercreate: get create-your-account supplier_code:{}".format(
            session.get('email_supplier_code', 'unknown')))
    form = EmailAddressForm()

    return render_template_with_csrf(
        "suppliers/create_your_account.html",
        form=form,
        email_address=session.get('account_email_address', '')
    )


@main.route('/create-your-account', methods=['POST'])
@debug_only
def submit_create_your_account():
    current_app.logger.info(
        "suppliercreate: post create-your-account supplier_code:{}".format(
            session.get('email_supplier_code', 'unknown')))
    form = EmailAddressForm(request.form)

    if form.validate():
        session['account_email_address'] = form.email_address.data
        return redirect(url_for(".company_summary"))
    else:
        return render_template_with_csrf(
            "suppliers/create_your_account.html",
            status_code=400,
            form=form,
            email_address=form.email_address.data
        )


@main.route('/company-summary', methods=['GET'])
@debug_only
def company_summary():
    return render_template_with_csrf(
        "suppliers/company_summary.html"
    )


@main.route('/company-summary', methods=['POST'])
@debug_only
def submit_company_summary():

    required_fields = [
        "email_address",
        "phone_number",
        "contact_name",
        "duns_number",
        "company_name",
        "account_email_address"
    ]

    missing_fields = [field for field in required_fields if field not in session]

    if not missing_fields:
        supplier = {
            "name": session["company_name"],
            "dunsNumber": str(session["duns_number"]),
            "contacts": [{
                "email": session["email_address"],
                "phoneNumber": session["phone_number"],
                "contactName": session["contact_name"]
            }]
        }

        if session.get("companies_house_number", None):
            supplier["companiesHouseNumber"] = session.get("companies_house_number")

        account_email_address = session.get("account_email_address", None)

        supplier = data_api_client.create_supplier(supplier)['supplier']
        session.clear()
        session['email_company_name'] = supplier['name']
        session['email_supplier_code'] = supplier['id']

        token = generate_supplier_invitation_token(
            name='',
            email_address=account_email_address,
            supplier_code=session['email_supplier_code'],
            supplier_name=session['email_company_name']
        )

        url = url_for('main.create_user', token=token, _external=True)

        email_body = render_template(
            "emails/create_user_email.html",
            company_name=session['email_company_name'],
            url=url
        )
        try:
            send_email(
                account_email_address,
                email_body,
                current_app.config['CREATE_USER_SUBJECT'],
                current_app.config['RESET_PASSWORD_EMAIL_FROM'],
                current_app.config['RESET_PASSWORD_EMAIL_NAME'],
                ["user-creation"]
            )
            session['email_sent_to'] = account_email_address
        except EmailError as e:
            current_app.logger.error(
                "suppliercreate.fail: Create user email failed to send. "
                "error {error} supplier_code {supplier_code} email_hash {email_hash}",
                extra={
                    'error': six.text_type(e),
                    'supplier_code': session['email_supplier_code'],
                    'email_hash': hash_email(account_email_address)})
            abort(503, "Failed to send user creation email")

        data_api_client.create_audit_event(
            audit_type=AuditTypes.invite_user,
            object_type='suppliers',
            object_id=session['email_supplier_code'],
            data={'invitedEmail': account_email_address})

        return redirect(url_for('.create_your_account_complete'), 302)
    else:
        return render_template_with_csrf(
            "suppliers/company_summary.html",
            status_code=400,
            missing_fields=missing_fields
        )


@main.route('/create-your-account-complete', methods=['GET'])
@debug_only
def create_your_account_complete():
    if 'email_sent_to' in session:
        email_address = session['email_sent_to']
    else:
        email_address = "the email address you supplied"
    session.clear()
    session['email_sent_to'] = email_address
    return render_template_with_csrf(
        "suppliers/create_your_account_complete.html",
        email_address=email_address
    )


@main.route('/duns-number', methods=['GET'])
@debug_only
def duns_number():
    form = DunsNumberForm()

    if form.duns_number.name in session:
        form.duns_number.data = session[form.duns_number.name]

    return render_template_with_csrf(
        "suppliers/duns_number.html",
        form=form
    ), 200


@main.route('/duns-number', methods=['POST'])
@debug_only
def submit_duns_number():
    form = DunsNumberForm(request.form)

    if form.validate():

        suppliers = data_api_client.find_suppliers(duns_number=form.duns_number.data)
        if len(suppliers["suppliers"]) > 0:
            form.duns_number.errors = ["DUNS number already used"]
            current_app.logger.warning(
                "suppliercreate.fail: duns:{duns} {duns_errors}",
                extra={
                    'duns': form.duns_number.data,
                    'duns_errors': ",".join(form.duns_number.errors)})
            return render_template(
                "suppliers/duns_number.html",
                form=form
            ), 400
        session[form.duns_number.name] = form.duns_number.data
        return redirect(url_for(".companies_house_number"))
    else:
        current_app.logger.warning(
            "suppliercreate.fail: duns:{duns} {duns_errors}",
            extra={
                'duns': form.duns_number.data,
                'duns_errors': ",".join(form.duns_number.errors)})
        return render_template(
            "suppliers/duns_number.html",
            form=form
        ), 400
